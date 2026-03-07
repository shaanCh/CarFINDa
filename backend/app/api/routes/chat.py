import uuid

from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Send a message to the LLM assistant and receive a reply.

    The assistant can answer questions about specific listings
    (referenced via ``listing_ids``) or general car-buying advice.

    TODO: Forward the message to the Gemini chat completion endpoint with
    system context that includes listing data and user preferences.
    """
    session_id = request.session_id or str(uuid.uuid4())

    # TODO: Build prompt with listing context if listing_ids provided
    # TODO: Call Gemini / LangChain agent for response
    # TODO: Persist conversation history keyed by session_id

    stub_reply = (
        f"I received your message: \"{request.message}\". "
        "This is a stub response. The real LLM assistant will be wired in soon."
    )

    return ChatResponse(
        message=stub_reply,
        session_id=session_id,
    )
