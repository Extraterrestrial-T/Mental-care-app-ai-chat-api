import os 
import dotenv
import faiss
from typing import Literal, TypedDict, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from pathlib import Path
from langchain_community.document_loaders import RecursiveUrlLoader
from bs4 import BeautifulSoup as Soup
from langgraph.checkpoint.redis.aio import AsyncRedisSaver 
from langgraph.store.redis.aio import AsyncRedisStore  
from langgraph.store.base import BaseStore
from redis.asyncio import Redis as AsyncRedisClient

# --- ENVIRONMENT & CONFIG ---
dotenv.load_dotenv()
DB_URI = os.getenv("REDIS_URL", None)

# --- MODEL INITIALIZATION ---
model = init_chat_model("google_genai:gemini-2.5-flash") 

# --- RAG SETUP ---
#PROJECT_ROOT = Path(__file__).parent
#FILE_PATH = os.path.join(PROJECT_ROOT, "corpus.txt")

#loader = TextLoader(file_path=FILE_PATH, encoding="utf-8")
loader = RecursiveUrlLoader(
    url="https://cornerhealth.org",
    max_depth=2,                          # Depth of recursion
    exclude_dirs=["/_sources", "/_modules","https://cornerhealth.org/wp-content/","https://cornerhealth.org/wp-includes/","https://cornerhealth.org/wp-json/"], # Skip these subdirectories
    extractor=lambda x: Soup(x, "html.parser").get_text(" ", strip=True),
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }, 
    prevent_outside=True                  
)

docs = loader.load()
#print(docs)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

embedding = HuggingFaceEmbeddings(model_name=EMBED_MODEL_ID)
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=20)
texts = text_splitter.split_documents(docs)
embedding_dim = len(embedding.embed_query("hello world"))
index = faiss.IndexFlatL2(embedding_dim)

vector_store = FAISS(
    embedding_function=embedding,
    index=index,
    docstore=InMemoryDocstore(),
    index_to_docstore_id={},
)
vector_store.add_documents(documents=texts)

# --- TOOLS ---

def rag_tool(query: str) -> list[str]:
    """Use this tool to answer questions about the mental health facility's website and services."""
    retrieved_docs = vector_store.similarity_search(query, k=2)
    return [i.page_content for i in retrieved_docs]

# --- STATE & SCHEMAS ---

class RequestClassification(TypedDict):
    intent: Literal["inquiry", "booking", "urgent_help", "conversational"]
    urgency: Literal["stable", "critical"]
    summary_request: str

class ReformattedQuery(TypedDict):
    new_query: str

class Response(TypedDict):
    response: str
    
class MentalHealthAgentState(TypedDict):
    """The agent state, using add_messages for history persistence."""
    
    user_message: str
    user_Fname: str | None
    user_Lname: str | None
    user_email: str | None
    user_phonenumber: str | None
    hospital_id: str | None  # NEW: Track which hospital
    classification: RequestClassification | None
    search_results: list[str] | None 
    response: str | None
    booking_initiated: bool  # NEW: Flag to trigger frontend booking UI
    messages: Annotated[list[AnyMessage], add_messages]
    
# --- ASYNC NODES ---

async def read_request(state: MentalHealthAgentState) -> dict:
    """Adds the current user_message to the message history."""
    return {
        "messages": [HumanMessage(content=state['user_message'])]
    }

async def classify_intent(state: MentalHealthAgentState) -> Command[Literal["search_website_info", "collect_booking_info", "respond"]]:
    """Uses LLM to classify request intent and urgency."""
    structured_llm = model.with_structured_output(RequestClassification)

    classification_prompt = f"""
    You are an expert mental health support agent.
    Your job is to analyze this request and classify it by intent and urgency.
    intent can be one of: inquiry, booking, urgent_help, conversational.
    request for rescheduling are not conversational but rather a booking intent.
    urgency can be one of: stable, critical.
    conversational intent is for friendly, empathetic small talk only and general emotional support you can use it to suggest coping strategies for down moods or for dealing with interpersonal relationships that do not indicate self harm and conversations.
    Please pay special attention to requests indicating immediate danger, suicide ideation, or self-harm, or a depressive mode and tone.
    Classify this request accordingly
    Request: {state['user_message']}
    """

    classification = await structured_llm.ainvoke(classification_prompt)
    classification_dict = classification
    
    if classification_dict['intent'] == 'urgent_help' or classification_dict['urgency'] == 'critical':
        goto = "respond"
    elif classification_dict['intent'] == 'inquiry':
        goto = "search_website_info" 
    elif classification_dict['intent'] == 'booking':
        goto = "collect_booking_info"
    elif classification_dict['intent'] == 'conversational':
        goto = "respond"
    
    return Command(
        update={"classification": classification},
        goto=goto
    )

async def search_website_info(state: MentalHealthAgentState) -> Command[Literal["respond"]]:
    """Search knowledge base for relevant information (RAG)."""
    structured_llm = model.with_structured_output(ReformattedQuery)
    prompt = f"""Rewrite this user query into a more effective query about the mental health facilities website
    Request:{state['user_message']}"""
    
    query = await structured_llm.ainvoke(prompt)
    query_dict = query
    
    try:
        search_results = rag_tool(query_dict["new_query"])
    except Exception as e:
        search_results = [f"RAG search failed: {e}"]

    return Command(
        update={"search_results": search_results},
        goto="respond"
    )

async def collect_booking_info(state: MentalHealthAgentState) -> Command[Literal["respond", "collect_booking_info"]]:
    """Collect patient information for booking (self-loop pattern)."""
    print("Collecting booking info node executing...")
    
    # 1. First Name Check
    if not state.get("user_Fname"):
        user_input = interrupt({
            "type": "user_Fname",
            "message": "User First name Required",
            "request": "Before I proceed to book your appointment I'll need your first name"
        })
        return Command(
            update={"user_Fname": user_input},
            goto="collect_booking_info"
        )
    
    # 2. Last Name Check
    if not state.get("user_Lname"):
        user_input = interrupt({
            "type": "user_Lname",
            "message": "User Last name Required",
            "request": "Next, I'll need your Last name"
        })
        return Command(
            update={"user_Lname": user_input},
            goto="collect_booking_info"
        )
        
    # 3. Phone Number Check
    if not state.get("user_phonenumber"):
        user_input = interrupt({
            "type": "user_phonenumber",
            "message": "User phone number Required",
            "request": "I'll also need your phone number to send appointment reminders"
        })
        return Command(
            update={"user_phonenumber": user_input},
            goto="collect_booking_info"
        )
        
    # 4. Email Check
    if not state.get("user_email"):
        user_input = interrupt({
            "type": "user_email",
            "message": "User email Required",
            "request": "And finally I'll need your email address so we can keep in touch"
        })
        return Command(
            update={"user_email": user_input},
            goto="collect_booking_info"
        )

    # All info collected - signal frontend to show doctor selection
    return Command(
        update={'booking_initiated': True},
        goto="respond"
    )

async def respond(state: MentalHealthAgentState) -> dict:
    """Creates the final response using all gathered information."""
    
    history_str = "\n".join([f"{msg.type.capitalize()}: {msg.content}" for msg in state.get("messages", [])])

    prompt = f"""
    You are a mental health support chatbot named CeCe for a nonprofit youth health organization, Corner Health.
    Your purpose is to respond gently, clearly, and safely. You do NOT give
    medical advice or instructions. You only provide emotional support,
    general information about services, and guidance on how to reach human help.

    You will be given a JSON-like agent state containing:
    - user_message
    - user_Fname, user_Lname
    - user_email, user_phonenumber
    - classification {state['classification']}
    - search_results (RAG chunks)
    - messages (conversation memory)
    - booking_initiated (whether we're ready for doctor selection)

    Your job is to produce the safest and most helpful response possible.

    -------------------------
    ### SAFETY RULES (VERY IMPORTANT)
    1. If classification.intent == "urgent_help" OR classification.urgency == "critical":
        - Do NOT describe self-harm.
        - Do NOT analyze methods or details.
        - Do NOT give medical or diagnostic guidance.
        - You MUST respond with supportive language AND direct them to immediate human help.
        - YOU MUST ALWAYS include this support line: "0800-123-HELP" for them to reach out to.
        - Encourage them to contact a trusted adult, friend, or local emergency services.
        - Be calm, warm, and brief.

    2. If intent == "booking" and booking_initiated == True:
        - Inform the user that you've gathered their information
        - Tell them they'll now see available doctors to choose from
        - Keep the tone supportive and simple
        - Don't ask for more information as booking is handled by the calendar UI

    3. If intent == "inquiry":
        - Use RAG search results to give safe, non-clinical information about services.
        - Do not describe mental health conditions.
        - Keep answers short and clear.

    4. If intent == "conversational":
        - Give friendly and empathetic small talk.
        - Redirect gently toward available services when appropriate.

    -------------------------
    ### RESPONSE STYLE RULES
    - Warm, neutral, respectful tone.
    - No clinical claims. No diagnosis. No referencing medical severity.
    - Short paragraphs. Clear sentences.
    - No judgmental wording.
    - Use the user's first name when available.

    -------------------------
    ### INFORMATION YOU MAY USE
    You may use the following RAG search results to explain how the organization works
    or what services are available. These contain general service descriptions only:
    {state.get("search_results", None)}
    
    ### Past Conversation History
    {state.get("messages")}

    -------------------------
    ### NOW PRODUCE THE RESPONSE 

    Generate a final response to the user based on:
    - Their original message: "{state["user_message"]}"
    - The classified intent: {state["classification"]['intent']}
    - The urgency: {state["classification"]['urgency']}
    - History: {state.get("messages")}
    - RAG search results: {state.get("search_results", None)}
    - Booking initiated: {state.get('booking_initiated', False)}

    Be safe, supportive, and helpful.
    """
    
    structured_llm = model.with_structured_output(Response)
    response_obj = await structured_llm.ainvoke(prompt)
    
    final_text = response_obj["response"]
    
    # Return with booking_initiated flag preserved
    return {
        "messages": [AIMessage(content=final_text)],
        "response": final_text,
        "booking_initiated": state.get('booking_initiated', False)
    }
    
# --- GRAPH COMPILATION (Async Context) ---

async def get_agent_app():
    """Initializes Redis and compiles the LangGraph agent asynchronously."""
    
    async with (
        AsyncRedisStore.from_conn_string(DB_URI) as store,
        AsyncRedisClient.from_url(DB_URI) as redis_client,
        AsyncRedisSaver.from_conn_string(DB_URI) as memory_saver
    ):
        
        workflow = StateGraph(MentalHealthAgentState)
        workflow.add_node("read_request", read_request)
        workflow.add_node("classify_intent", classify_intent)
        workflow.add_node("search_website_info", search_website_info)
        workflow.add_node("collect_booking_info", collect_booking_info)
        workflow.add_node("respond", respond)

        workflow.add_edge(START, "read_request")
        workflow.add_edge("read_request", "classify_intent")
        workflow.add_edge("respond", END)
        
        workflow.add_conditional_edges(
            "classify_intent", 
            lambda x: x["classification"]["intent"],
            {
                "urgent_help": "respond",
                "inquiry": "search_website_info",
                "booking": "collect_booking_info",
                "conversational": "respond"
            }
        )
        
        mental_health_agent_app = workflow.compile(checkpointer=memory_saver, store=store)
        
        return mental_health_agent_app, redis_client