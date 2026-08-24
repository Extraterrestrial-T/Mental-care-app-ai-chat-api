import os 
import dotenv
import faiss
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, Annotated
from pydantic import BaseModel
from langgraph.graph import StateGraph, END, START
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from pathlib import Path
from langchain_community.document_loaders import RecursiveUrlLoader
from bs4 import BeautifulSoup as Soup
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver 
from langgraph.store.redis.aio import AsyncRedisStore  
from redis.asyncio import Redis as AsyncRedisClient
from app.config import settings
from app.agent.booking_logic import (
    apply_message_corrections,
    closing_response,
    extract_age_from_message as _extract_age_from_message,
    is_gratitude,
    normalize_contact_details,
    parse_age as _parse_age,
    requests_booking,
    safety_status as _safety_status,
)

# --- ENVIRONMENT & CONFIG ---
dotenv.load_dotenv()
DB_URI = settings.REDIS_URL or None
PROJECT_ROOT = Path(__file__).parent
LOCAL_CORPUS_PATH = PROJECT_ROOT / "corpus.txt"
RAG_INDEX_DIR = Path(settings.RAG_INDEX_DIR)
RAG_SOURCE_URL = settings.RAG_SOURCE_URL
CHAT_MODEL = settings.CHAT_MODEL
CRISIS_SUPPORT_LINE = settings.CRISIS_SUPPORT_LINE.strip()
MIN_ELIGIBLE_AGE = settings.MIN_ELIGIBLE_AGE
MAX_ELIGIBLE_AGE = settings.MAX_ELIGIBLE_AGE

# --- MODEL INITIALIZATION ---
model = init_chat_model(CHAT_MODEL)

# --- RAG SETUP ---
os.environ["TOKENIZERS_PARALLELISM"] = "false"
EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
embedding = None
vector_store = None


def get_embedding_model() -> HuggingFaceEmbeddings:
    """Load the embedding model once per process."""
    global embedding
    if embedding is None:
        embedding = HuggingFaceEmbeddings(model_name=EMBED_MODEL_ID)
    return embedding


def _load_source_documents():
    """Load the locally versioned corpus, falling back to the configured website."""
    if LOCAL_CORPUS_PATH.exists():
        return TextLoader(file_path=str(LOCAL_CORPUS_PATH), encoding="utf-8").load()

    loader = RecursiveUrlLoader(
        url=RAG_SOURCE_URL,
        max_depth=2,
        exclude_dirs=[
            "/_sources",
            "/_modules",
            f"{RAG_SOURCE_URL}/wp-content/",
            f"{RAG_SOURCE_URL}/wp-includes/",
            f"{RAG_SOURCE_URL}/wp-json/",
        ],
        extractor=lambda x: Soup(x, "html.parser").get_text(" ", strip=True),
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        prevent_outside=True,
    )
    return loader.load()


def load_vector_store(rebuild: bool = False) -> FAISS:
    """Load the persisted FAISS index; rebuilding is an explicit maintenance action."""
    global vector_store
    if vector_store is not None:
        return vector_store

    embeddings = get_embedding_model()
    index_file = RAG_INDEX_DIR / "index.faiss"

    if index_file.exists() and not rebuild:
        vector_store = FAISS.load_local(
            folder_path=str(RAG_INDEX_DIR),
            embeddings=embeddings,
            allow_dangerous_deserialization=True,
        )
        return vector_store

    if not rebuild:
        raise RuntimeError(
            f"RAG index is missing at {RAG_INDEX_DIR}. "
            "Build it before starting the API with: python -m app.agent.build_rag_index"
        )

    docs = _load_source_documents()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=20)
    texts = text_splitter.split_documents(docs)
    embedding_dim = len(embeddings.embed_query("hello world"))
    index = faiss.IndexFlatL2(embedding_dim)

    vector_store = FAISS(
        embedding_function=embeddings,
        index=index,
        docstore=InMemoryDocstore(),
        index_to_docstore_id={},
    )
    vector_store.add_documents(documents=texts)
    RAG_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(str(RAG_INDEX_DIR))
    return vector_store

# --- TOOLS ---

def rag_tool(query: str) -> list[str]:
    """Use this tool to answer questions about the mental health facility's website and services."""
    store = load_vector_store()
    retrieved_docs = store.similarity_search(query, k=2)
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


class BookingIntakeFacts(BaseModel):
    """Facts explicitly stated in an initial booking message, never inferred."""

    feeling: str | None = None
    support_needed: str | None = None
    safety: Literal["safe", "unsafe", "unknown"] = "unknown"


class MentalHealthAgentState(TypedDict):
    """The agent state, using add_messages for history persistence."""
    
    user_message: str
    user_age: int | None
    user_Fname: str | None
    user_Lname: str | None
    user_email: str | None
    user_phonenumber: str | None
    sms_call_consent: str | None
    intake_feeling: str | None
    intake_support_needed: str | None
    intake_safety_check: str | None
    intake_staff_notes: str | None
    eligibility_status: Literal["eligible", "ineligible"] | None
    booking_intake_extracted: bool | None
    correction_detected: bool | None
    safety_guidance_acknowledged: bool | None
    booking_completed: bool | None
    hospital_id: str | None  # NEW: Track which hospital
    classification: RequestClassification | None
    search_results: list[str] | None 
    response: str | None
    booking_initiated: bool  # NEW: Flag to trigger frontend booking UI
    messages: Annotated[list[AnyMessage], add_messages]
    
# --- ASYNC NODES ---

async def read_request(state: MentalHealthAgentState) -> dict:
    """Adds the current user_message to the message history."""
    message = state["user_message"]
    updates: dict[str, Any] = {
        "messages": [HumanMessage(content=message)],
    }

    # Corrections must be applied before intent classification. Otherwise an age
    # clarification is treated as small talk and the completed graph never reopens.
    updates.update(apply_message_corrections(state, message))
    return updates

async def classify_intent(state: MentalHealthAgentState) -> Command[Literal["search_website_info", "collect_booking_info", "respond"]]:
    """Uses LLM to classify request intent and urgency."""
    if state.get("correction_detected"):
        classification: RequestClassification = {
            "intent": "booking",
            "urgency": "stable",
            "summary_request": "The user corrected booking information.",
        }
        return Command(update={"classification": classification}, goto="collect_booking_info")

    if is_gratitude(state["user_message"]):
        classification = {
            "intent": "conversational",
            "urgency": "stable",
            "summary_request": "The user is closing the conversation with thanks.",
        }
        return Command(
            update={"classification": classification, "booking_initiated": False},
            goto="respond",
        )

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
    
    if requests_booking(state["user_message"]):
        classification_dict["intent"] = "booking"
        goto = "collect_booking_info"
    elif classification_dict['intent'] == 'urgent_help' or classification_dict['urgency'] == 'critical':
        goto = "respond"
    elif classification_dict['intent'] == 'inquiry':
        goto = "search_website_info" 
    elif classification_dict['intent'] == 'booking':
        goto = "collect_booking_info"
    elif classification_dict['intent'] == 'conversational':
        goto = "respond"
    
    updates: dict[str, Any] = {"classification": classification}
    if classification_dict["intent"] == "booking":
        updates.update({"booking_initiated": False, "booking_completed": False})

    return Command(
        update=updates,
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


def _extract_resume_value(user_input: Any, field_name: str) -> Any:
    """Normalize LangGraph interrupt resume payloads from the frontend."""
    if isinstance(user_input, dict):
        return user_input.get(field_name)
    return user_input


async def _extract_booking_intake_facts(message: str) -> BookingIntakeFacts:
    """Extract only information the user has already volunteered in one message."""
    structured_llm = model.with_structured_output(BookingIntakeFacts)
    return await structured_llm.ainvoke(
        """
        Extract booking-intake facts from the user's message. Do not infer facts,
        do not diagnose, and leave a field empty when it was not explicitly stated.
        - feeling: the user's own description of how they have been feeling.
        - support_needed: the support or service they say they want.
        - safety: unsafe only if they explicitly say they are unsafe, in danger, or
          do not feel safe; safe only if they explicitly say they are safe; otherwise unknown.

        User message:
        """ + message
    )


def _crisis_response() -> str:
    support_line = f" You can also contact {CRISIS_SUPPORT_LINE}." if CRISIS_SUPPORT_LINE else ""
    return (
        "I'm sorry you're feeling unsafe. Please contact local emergency services now, "
        "or go to the nearest emergency department. If you can, tell a parent, guardian, "
        f"or another trusted adult and stay with someone.{support_line}"
    )


def _contact_state_updates(payload: Any) -> dict[str, Any]:
    """Validate the contact form payload and map it onto persisted agent state."""
    return normalize_contact_details(payload)


async def collect_booking_info(state: MentalHealthAgentState) -> Command[Literal["respond", "collect_booking_info"]]:
    """Collect patient information for booking (self-loop pattern)."""
    print("Collecting booking info node executing...")

    # Extract facts already volunteered in the initial booking request once.
    if not state.get("booking_intake_extracted"):
        facts = await _extract_booking_intake_facts(state["user_message"])
        extracted_age = _extract_age_from_message(state["user_message"])
        updates: dict[str, Any] = {"booking_intake_extracted": True}
        if extracted_age is not None and not state.get("user_age"):
            updates["user_age"] = extracted_age
        if facts.feeling and not state.get("intake_feeling"):
            updates["intake_feeling"] = facts.feeling
        if facts.support_needed and not state.get("intake_support_needed"):
            updates["intake_support_needed"] = facts.support_needed
        if facts.safety != "unknown" and not state.get("intake_safety_check"):
            updates["intake_safety_check"] = facts.safety
        return Command(update=updates, goto="collect_booking_info")

    # 1. Age gate for the Corner Health MVP.
    if not state.get("user_age"):
        user_input = interrupt({
            "type": "user_age",
            "message": "Age Required",
            "request": "Before I help with booking, how old are you?"
        })
        age_value = _extract_resume_value(user_input, "user_age")
        return Command(
            update={"user_age": age_value},
            goto="collect_booking_info"
        )

    age = _parse_age(state.get("user_age"))
    if age is None or age < MIN_ELIGIBLE_AGE or age > MAX_ELIGIBLE_AGE:
        return Command(
            update={"eligibility_status": "ineligible", "booking_initiated": False},
            goto="respond"
        )

    # 2. Safety is always checked immediately after eligibility.
    if not state.get("intake_safety_check"):
        user_input = interrupt({
            "type": "intake_safety_check",
            "message": "Safety Check",
            "request": "Before we continue, are you feeling safe right now?"
        })
        return Command(
            update={"intake_safety_check": _extract_resume_value(user_input, "intake_safety_check")},
            goto="collect_booking_info"
        )

    if (
        _safety_status(state.get("intake_safety_check")) == "unsafe"
        and not state.get("safety_guidance_acknowledged")
    ):
        user_input = interrupt({
            "type": "unsafe_booking_acknowledgement",
            "message": "Urgent safety guidance",
            "request": (
                f"{_crisis_response()} This booking service is not emergency care. "
                "You can continue arranging a non-emergency appointment after acknowledging this guidance."
            ),
        })
        acknowledged = _extract_resume_value(user_input, "unsafe_booking_acknowledgement") is True
        return Command(
            update={"safety_guidance_acknowledged": bool(acknowledged)},
            goto="collect_booking_info" if acknowledged else "respond",
        )

    # 3. Collect only intake details that were not already volunteered.
    if not state.get("intake_feeling"):
        user_input = interrupt({
            "type": "intake_feeling",
            "message": "Intake Question",
            "request": "Thanks. How have you been feeling recently?"
        })
        return Command(
            update={"intake_feeling": _extract_resume_value(user_input, "intake_feeling")},
            goto="collect_booking_info"
        )

    if not state.get("intake_support_needed"):
        user_input = interrupt({
            "type": "intake_support_needed",
            "message": "Intake Question",
            "request": "What kind of support are you hoping to get from the clinic?"
        })
        return Command(
            update={"intake_support_needed": _extract_resume_value(user_input, "intake_support_needed")},
            goto="collect_booking_info"
        )

    if not state.get("intake_staff_notes"):
        user_input = interrupt({
            "type": "intake_staff_notes",
            "message": "Intake Question",
            "request": "Is there anything you would like the care team to know before your appointment?"
        })
        return Command(
            update={"intake_staff_notes": _extract_resume_value(user_input, "intake_staff_notes")},
            goto="collect_booking_info"
        )

    # 4. Collect contact details in one validated form instead of four chat turns.
    if not all(
        state.get(field)
        for field in ("user_Fname", "user_Lname", "user_phonenumber", "user_email", "sms_call_consent")
    ):
        user_input = interrupt({
            "type": "contact_details",
            "message": "Contact details",
            "request": "Enter your contact details so the clinic can confirm your appointment.",
            "phone_hint": "+1 734 555 0123",
        })
        return Command(
            update=_contact_state_updates(user_input),
            goto="collect_booking_info"
        )

    # All info collected - signal frontend to show doctor selection
    return Command(
        update={'eligibility_status': "eligible", 'booking_initiated': True},
        goto="respond"
    )

async def respond(state: MentalHealthAgentState) -> dict:
    """Creates the final response using all gathered information."""

    classification = state.get("classification") or {}
    if (
        classification.get("intent") == "urgent_help"
        or (
            classification.get("urgency") == "critical"
            and not state.get("safety_guidance_acknowledged")
        )
        or (
            _safety_status(state.get("intake_safety_check")) == "unsafe"
            and not state.get("safety_guidance_acknowledged")
        )
    ):
        return {
            "messages": [AIMessage(content=_crisis_response())],
            "response": _crisis_response(),
            "booking_initiated": False,
        }

    closing_text = closing_response(
        state["user_message"],
        booking_completed=bool(state.get("booking_completed")),
    )
    if closing_text:
        return {
            "messages": [AIMessage(content=closing_text)],
            "response": closing_text,
            "booking_initiated": False,
        }

    if classification.get("intent") == "booking" and state.get("eligibility_status") == "ineligible":
        text = (
            f"Corner Health currently books patients ages {MIN_ELIGIBLE_AGE} to {MAX_ELIGIBLE_AGE}. "
            "If the age you entered was incorrect, tell me the corrected age. Otherwise, please contact "
            "the clinic directly for alternate support."
        )
        return {"messages": [AIMessage(content=text)], "response": text, "booking_initiated": False}

    if classification.get("intent") == "booking" and state.get("booking_initiated"):
        text = "Thanks. Your intake information is ready. Choose an available doctor and time below."
        return {"messages": [AIMessage(content=text)], "response": text, "booking_initiated": True}
    
    history_str = "\n".join([f"{msg.type.capitalize()}: {msg.content}" for msg in state.get("messages", [])])

    prompt = f"""
    You are a mental health support chatbot named CeCe for a nonprofit youth health organization, Corner Health.
    Your purpose is to respond gently, clearly, and safely. You do NOT give
    medical advice or instructions. You only provide emotional support,
    general information about services, and guidance on how to reach human help.

    You will be given a JSON-like agent state containing:
    - user_message
    - user_age and eligibility_status
    - intake_feeling, intake_support_needed, intake_safety_check, intake_staff_notes
    - user_Fname, user_Lname
    - user_email, user_phonenumber
    - classification {state['classification']}
    - search_results (RAG chunks)
    - messages (conversation memory)
    - booking_initiated (whether we're ready for doctor selection)

    Your job is to produce the safest and most helpful response possible.

    -------------------------
    ### SAFETY RULES (VERY IMPORTANT)
    1. If intent == "booking" and eligibility_status == "ineligible":
        - Do not continue booking.
        - Explain that this service is designed for young people ages {MIN_ELIGIBLE_AGE} to {MAX_ELIGIBLE_AGE}.
        - Encourage them to contact the clinic directly for guidance or alternate resources.
        - Keep the tone respectful and brief.

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
    - Eligibility status: {state.get("eligibility_status")}
    - Age: {state.get("user_age")}
    - Intake feeling: {state.get("intake_feeling")}
    - Support requested: {state.get("intake_support_needed")}
    - Safety check answer: {state.get("intake_safety_check")}
    - Staff notes: {state.get("intake_staff_notes")}
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

@dataclass
class AgentRuntimeResources:
    """Owns long-lived agent resources that need explicit shutdown."""

    redis_client: Any = None
    store_cm: Any = None
    saver_cm: Any = None

    @property
    def redis_connected(self) -> bool:
        return self.redis_client is not None

    async def close(self):
        if self.redis_client is not None:
            await self.redis_client.aclose()
        if self.saver_cm is not None:
            await self.saver_cm.__aexit__(None, None, None)
        if self.store_cm is not None:
            await self.store_cm.__aexit__(None, None, None)


def _build_workflow() -> StateGraph:
    workflow = StateGraph(MentalHealthAgentState)
    workflow.add_node("read_request", read_request)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("search_website_info", search_website_info)
    workflow.add_node("collect_booking_info", collect_booking_info)
    workflow.add_node("respond", respond)

    workflow.add_edge(START, "read_request")
    workflow.add_edge("read_request", "classify_intent")
    workflow.add_edge("respond", END)

    return workflow


async def get_agent_app():
    """Compile the LangGraph agent and keep persistence resources alive."""
    # Load the model and persisted index before accepting chat traffic. This makes
    # a missing or uncached RAG asset a startup problem, never a mid-chat rebuild.
    load_vector_store()
    workflow = _build_workflow()

    if not DB_URI:
        print("WARNING: REDIS_URL is not set. Using in-memory LangGraph checkpointing.")
        return workflow.compile(checkpointer=MemorySaver()), AgentRuntimeResources()

    resources = AgentRuntimeResources()
    resources.store_cm = AsyncRedisStore.from_conn_string(DB_URI)
    resources.saver_cm = AsyncRedisSaver.from_conn_string(DB_URI)
    store = await resources.store_cm.__aenter__()
    memory_saver = await resources.saver_cm.__aenter__()
    resources.redis_client = AsyncRedisClient.from_url(DB_URI)

    mental_health_agent_app = workflow.compile(checkpointer=memory_saver, store=store)
    return mental_health_agent_app, resources
