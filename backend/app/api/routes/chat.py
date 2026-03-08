import uuid
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.dependencies import get_current_user
from app.models.schemas import ChatRequest, ChatResponse
from app.services.llm.gemini_client import GeminiClient
from app.services.llm.chat_agent import CarAssistant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory session store (replace with DB in production)
_sessions: dict[str, dict] = {}


def _get_or_create_session(session_id: str, context: dict | None = None) -> dict:
    session = _sessions.get(session_id, {
        "history": [],
        "context": context or {},
    })
    if context:
        session["context"].update(context)
    return session


async def _get_reply(request: ChatRequest, session: dict) -> str:
    """Get a reply from the LLM assistant (or fallback)."""
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        return (
            f"I received your message: \"{request.message}\". "
            "The LLM assistant requires a Gemini API key to be configured. "
            "Please set GEMINI_API_KEY in your .env file."
        )

    gemini = GeminiClient(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL,
    )
    assistant = CarAssistant(gemini=gemini)

    reply = await assistant.chat(
        message=request.message,
        conversation_history=session["history"],
        context=session["context"],
    )

    # Update session history
    session["history"].append({"role": "user", "content": request.message})
    session["history"].append({"role": "model", "content": reply})

    # Keep history bounded
    if len(session["history"]) > 40:
        session["history"] = session["history"][-30:]

    return reply


@router.post("/", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Send a message to the CarFINDa assistant and get a full reply."""
    session_id = request.session_id or str(uuid.uuid4())
    session = _get_or_create_session(session_id, request.context)

    try:
        reply = await _get_reply(request, session)
        _sessions[session_id] = session
        return ChatResponse(message=reply, session_id=session_id)
    except Exception as exc:
        logger.error("Chat agent error: %s", exc)
        return ChatResponse(
            message="Sorry, I encountered an error processing your request. Please try again.",
            session_id=session_id,
        )


@router.post("/stream")
async def stream_message(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Send a message and stream the reply via SSE word-by-word."""
    session_id = request.session_id or str(uuid.uuid4())
    session = _get_or_create_session(session_id, request.context)

    async def event_stream():
        try:
            reply = await _get_reply(request, session)
            _sessions[session_id] = session
        except Exception as exc:
            logger.error("Chat stream error: %s", exc)
            reply = "Sorry, I encountered an error processing your request."

        # Stream session ID first
        yield f'data: {json.dumps({"sessionId": session_id})}\n\n'

        # Stream words for typing effect
        words = reply.split(" ")
        for word in words:
            yield f'data: {json.dumps({"text": word + " "})}\n\n'
            await asyncio.sleep(0.03)

        yield 'data: [DONE]\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
