const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function POST(request: Request) {
  try {
    const { listingId, userMessage, sessionId, context } = await request.json();

    // Use the backend's /stream endpoint for real-time SSE
    const res = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMessage,
        listing_ids: listingId ? [listingId] : [],
        session_id: sessionId || null,
        context: context || undefined,
      }),
    });

    if (!res.ok) {
      console.error('Backend chat error:', res.status);
      return streamText(
        "I'm having trouble connecting to the backend service. Please try again in a moment."
      );
    }

    // Proxy the SSE stream directly from backend
    return new Response(res.body, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
      },
    });

  } catch (error) {
    console.error('Chat API error:', error);
    return streamText('Sorry, an error occurred. Please try again.');
  }
}

function streamText(text: string): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const words = text.split(' ');
      for (const word of words) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ text: word + ' ' })}\n\n`));
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      controller.enqueue(encoder.encode('data: [DONE]\n\n'));
      controller.close();
    }
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
    },
  });
}
