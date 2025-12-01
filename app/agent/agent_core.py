import os 
import dotenv
import random
import datetime
import faiss
from typing import Literal, TypedDict, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model # This uses synchronous clients
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from pathlib import Path
# --- ASYNC REDIS IMPORTS ---

from langgraph.checkpoint.redis.aio import AsyncRedisSaver 
from langgraph.store.redis.aio import AsyncRedisStore  
from langgraph.store.base import BaseStore
from redis.asyncio import Redis as AsyncRedisClient
# ---

# --- ENVIRONMENT & CONFIG ---
dotenv.load_dotenv()
# IMPORTANT: This needs to point to your async Redis instance
DB_URI = os.getenv("REDIS_URL", None)

# --- MODEL INITIALIZATION ---
# Langchain's init_chat_model handles asynchronous calls internally for providers like Google/Anthropic
model = init_chat_model("google_genai:gemini-2.5-flash") 

# --- RAG SETUP ---
PROJECT_ROOT = Path(__file__).parent  # Goes up to /agent
FILE_PATH= os.path.join(PROJECT_ROOT, "corpus.txt")

loader = TextLoader(file_path=FILE_PATH, encoding="utf-8")
docs = loader.load()

os.environ["TOKENIZERS_PARALLELISM"] = "false"
EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

embedding = HuggingFaceEmbeddings(model_name=EMBED_MODEL_ID)
text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=20)
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

# --- ASYNC TOOLS ---

# Note: We keep this synchronous for simplicity, but in a heavy production app, 
# FAISS searches should ideally be run in an executor or wrapped in an async function.
def rag_tool(query: str) -> list[str]:
    """Use this tool to answer questions about the mental health facility's website and services."""
    retrieved_docs = vector_store.similarity_search(query, k=2)
    return [i.page_content for i in retrieved_docs]

# The booking logic is CPU-bound but does not wait for I/O, so it can be async with little change.
async def book_appointment_algo(name: str, phonenumber: str|None, email: str|None) -> tuple[bool|Exception, str|None]:
    """Use this tool to book an appointment at the mental health facility."""
    print(f"Booking appointment for {name}, Phone: {phonenumber}, Email: {email}")
    status = False
    appointment_date = None
    
    # Existing date logic (synchronous and deterministic)
    try:
        date = datetime.datetime.now()
        year = date.year
        
        if int(date.day) < 28 and int(date.month) < 12:
            month = random.randint(int(date.month), 12)
            day = random.randint(int(date.day), 28)
        elif int(date.day) >= 28 and int(date.month) < 12:
            month = random.randint(int(date.month) + 1, 12)
            day = random.randint(1, 28)
        elif int(date.day) < 28 and int(date.month) == 12:
            year = date.year + 1
            month = random.randint(1, 12)
            day = random.randint(int(date.day), 28)
            
        appointment_date = f"{month}/{day}/{year}"
        status = True
    except Exception as e: 
        status = e
        
    return (status, appointment_date)

# --- STATE & SCHEMAS ---

class RequestClassification(TypedDict):
    intent: Literal["inquiry", "booking", "urgent_help","conversational"]
    urgency: Literal["stable", "critical"]
    summary_request: str

class ReformattedQuery(TypedDict):
    new_query: str

class Response(TypedDict):
    response: str
    
class MentalHealthAgentState(TypedDict):
    """The agent state, using add_messages for history persistence."""
    
    user_message: str
    user_Fname: str|None
    user_Lname: str|None
    user_email: str|None
    user_phonenumber: str|None
    booked: bool|Exception
    appointment_date: str|None
    classification: RequestClassification | None
    search_results: list[str] | None 
    response: str | None
    # Crucial: Use Annotated for automatic appending of conversation history
    messages: Annotated[list[AnyMessage], add_messages]
    
# --- ASYNC NODES ---

async def read_request(state: MentalHealthAgentState) -> dict:
    """Adds the current user_message to the message history."""
    # We use state['user_message'] which is passed directly from the FastAPI input
    return {
        "messages": [HumanMessage(content=state['user_message'])]
    }

async def classify_intent(state: MentalHealthAgentState) -> Command[Literal["search_website_info", "book_appointment","respond"]]:
    """Uses LLM to classify request intent and urgency."""
    structured_llm = model.with_structured_output(RequestClassification)

    # Format the prompt using the state's latest input
    classification_prompt = f"""
    You are an expert mental health support agent.
    Your job is to analyze this request and classify it by intent and urgency.
    intent can be one of: inquiry, booking, urgent_help, conversational.
    request for rescheduling are not conversational but rather a booking intent.
    urgency can be one of: stable, critical.
    conversational intent is for friendly, empathetic small talk only and general emotional support you csn use it to suggest coping strategies for down moods or for dealing with interpersonal relationships  that do not indicate self harm and conversations.
    Please pay special attention to requests indicating immediate danger, suicide ideation, or self-harm, or a deppressive mode and tone.
    Classify this request accordingly
    Request: {state['user_message']}
    """

    # Use ainvoke for asynchronous model call
    classification = await structured_llm.ainvoke(classification_prompt)
    classification_dict = classification
    
    if classification_dict['intent'] == 'urgent_help' or classification_dict['urgency'] == 'critical':
        goto = "respond"
    elif classification_dict['intent'] == 'inquiry':
        goto = "search_website_info" 
    elif classification_dict['intent'] == 'booking':
        goto = "book_appointment"
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
    
    # Use ainvoke for asynchronous model call
    query = await structured_llm.ainvoke(prompt)
    query_dict = query
    
    try:
        # Note: rag_tool is synchronous, but we treat it as fast I/O here.
        search_results = rag_tool(query_dict["new_query"])
    except Exception as e:
        search_results = [f"RAG search failed: {e}"]

    return Command(
        update={"search_results": search_results},
        goto="respond"
    )

async def book_appointment(state: MentalHealthAgentState) -> Command[Literal["respond", "book_appointment"]]:
    """Appointment scheduler with multiple interruption points (self-loop)."""
    print("Booking appointment node executing...")
    
    # 1. First Name Check
    if not state.get("user_Fname"):
        user_input = interrupt({
            "type": "user_Fname",
            "message": "User First name Required",
            "request": "Before I proceed to book your appointment I'll need your first name"
        })
        # The goto="book_appointment" is CRUCIAL for the self-loop
        return Command(
            update={"user_Fname": user_input},
            goto="book_appointment"
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
            goto="book_appointment"
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
            goto="book_appointment"
        )
        
    # 4. Email Check
    if not state.get("user_email"):
        user_input = interrupt({
            "type": "user_email",
            "message": "User email Required",
            "request": "And finally i'll need your email address so we can keep in touch"
        })
        return Command(
            update={"user_email": user_input},
            goto="book_appointment"
        )

    # 5. Finalize Booking (All data collected)
    name = f"{state['user_Fname']} {state['user_Lname']}"
    # Use await for the async tool
    is_booked, appointment_date = await book_appointment_algo(
        name=name, phonenumber=state['user_phonenumber'], email=state['user_email']
    )
    
    return Command(
        update={
            'booked': is_booked,
            'appointment_date': appointment_date
        },
        goto="respond"
    )

async def respond(state: MentalHealthAgentState) -> dict:
    """Creates the final response using all gathered information."""
    
    # --- Prompt Construction ---
    # The history must be included in the prompt for context
    history_str = "\n".join([f"{msg.type.capitalize()}: {msg.content}" for msg in state.get("messages", [])])

    prompt = f"""
     You are a mental health support chatbot for a nonprofit organization.
        Your purpose is to respond gently, clearly, and safely. You do NOT give
        medical advice or instructions. You only provide emotional support,
        general information about services, and guidance on how to reach human help.

        You will be given a JSON-like agent state containing:
        - user_message
        - user_Fname, user_Lname
        - user_email, user_phonenumber
        - preferred_month
        - classification {state['classification'] }
        - search_results (RAG chunks)
        - messages (conversation memory)

        Your job is to produce the safest and most helpful response possible.

        -------------------------
        ### SAFETY RULES (VERY IMPORTANT)
        1. If classification.intent == "urgent_help" OR classification.urgency == "critical":
            - Do NOT describe self-harm.
            - Do NOT analyze methods or details.
            - Do NOT give medical or diagnostic guidance.
            - You MUST respond with supportive language AND direct them to immediate human help.
            - YOU MUST  ALWAYS include this support line: "0800-123-HELP" for them to reach out to."
            - Encourage them to contact a trusted adult, friend, or local emergency services.
            - Be calm, warm, and brief.

        2. If intent == "booking":
            - Confirm the appointment booking using, don't ask about information as the booking is handles by another node
            - booking details{state.get('booked', None), state.get('appointment_date', None)}
            - Keep the tone supportive and simple.
            - Do not provide clinical input.
            - if the booking failed apologize and suggest trying again later else if it was successful provide the appointment date.

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
        {state.get("search_results",None)}
        ### Past Conversation History
        {state.get("messages")}

        -------------------------
        ### NOW PRODUCE THE RESPONSE 

        Generate a final response to the user based on:
        - Their original message: "{state["user_message"]}"
        - The classified intent: {state["classification"]['intent']}
        - The urgency: {state["classification"]['urgency']}
        - History : {state.get("messages")}
        - RAG search results: {state.get("search_results",None)}
        remmber all of these  queries have been precomputed in other nodes of this work flow, don't try to or ask the user for info here recompute them here.
        - Booking details: {state.get('booked', None), state.get('appointment_date', None)}

        Be safe, supportive, and helpful.
        """
    
    structured_llm = model.with_structured_output(Response)
    # Use ainvoke for asynchronous model call
    response_obj = await structured_llm.ainvoke(prompt)
    
    final_text = response_obj["response"]
    
    # CRUCIAL: Return the AIMessage to be saved in the history (messages: Annotated[..., add_messages])
    return {
        "messages": [AIMessage(content=final_text)],
        "response": final_text 
    }
    
# --- GRAPH COMPILATION (Async Context) ---

# We define this function to be called from app.py on startup.
async def get_agent_app():
    """Initializes Redis and compiles the LangGraph agent asynchronously."""
    
    # 1. Setup Redis Checkpointer
    # NOTE: We use the AsyncRedisSaver which is designed for concurrent apps like FastAPI.
    async with (
        AsyncRedisStore.from_conn_string(DB_URI) as store,
        AsyncRedisClient.from_url(DB_URI) as redis_client,
         AsyncRedisSaver.from_conn_string(DB_URI) as memory_saver
    ):
        

        # 2. Build the workflow
        workflow = StateGraph(MentalHealthAgentState)
        workflow.add_node("read_request", read_request)
        workflow.add_node("classify_intent", classify_intent)
        workflow.add_node("search_website_info", search_website_info)
        workflow.add_node("book_appointment", book_appointment)
        workflow.add_node("respond", respond)

        # 3. Add Edges
        workflow.add_edge(START, "read_request")
        workflow.add_edge("read_request", "classify_intent")
        workflow.add_edge("respond", END)
        
        # Conditional Edges from Classify
        workflow.add_conditional_edges(
            "classify_intent", 
            lambda x: x["classification"]["intent"],
            {
                "urgent_help": "respond",
                "inquiry": "search_website_info",
                "booking": "book_appointment",
                "conversational": "respond"
            }
        )
        
        # 4. Compile the Agent
        mental_health_agent_app = workflow.compile(checkpointer=memory_saver, store=store)
        
        # We need a different pattern for returning the compiled graph from an async context.
        # Typically, the Redis client is passed and managed by the caller (FastAPI).
        return mental_health_agent_app, redis_client 


# Since the compilation happens in an async function, we will initialize 
# and expose a global variable in app.py to hold the compiled graph.
# The 'get_agent_app' function is what you will import and call from FastAPI.