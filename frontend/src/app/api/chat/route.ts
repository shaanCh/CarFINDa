export async function POST(request: Request) {
  const BACKEND_URL = 'http://127.0.0.1:8000';

  try {
    const { listingId, userMessage } = await request.json();

    const res = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
         message: userMessage,
         listing_ids: [listingId],
         session_id: null // handled by backend
      })
    });

    if (!res.ok) {
       return new Response(JSON.stringify({ error: 'Backend streaming error' }), { status: res.status });
    }

    // Proxy the stream back to the client directly
    return new Response(res.body, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
      },
    });

  } catch(error) {
     return new Response(JSON.stringify({ error: 'proxy failed' }), { status: 500 });
  }
}
