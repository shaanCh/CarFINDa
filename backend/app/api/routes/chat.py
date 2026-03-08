import uuid
import asyncio

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

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


@router.post("/stream")
async def stream_message(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Send a message and stream the reply via SSE.

    TODO: Yield responses from Gemini streaming completions.
    """
    async def event_stream():
        # Stub streaming response matching frontend's mock
        await asyncio.sleep(0.6)
        
        message_topic = 'the price' if hasattr(request, 'message') and 'price' in request.message.lower() else 'this car'
        listing_str = request.listing_ids[0] if request.listing_ids else "unknown"
        
        response_text = (
            f"That's a great question about {message_topic} (ID: {listing_str}). "
            "Based on our analysis, this is a solid choice. The numbers look good given the current market, "
            "and its reliability score is in range. \n\nHowever, always make sure to ask for maintenance records before purchasing. "
            "Do you want to know more about similar cars, or do you want negotiation tips?"
        )
        
        words = response_text.split(" ")
        for word in words:
            yield f'data: {{"text": "{word} "}}\n\n'
            await asyncio.sleep(0.03)
            
        yield 'data: [DONE]\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )
