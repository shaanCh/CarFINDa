import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { action, ...payload } = body;

    // Route to the correct backend endpoint
    const endpoints: Record<string, string> = {
      subscribe: '/api/notifications/subscribe',
      'outreach-summary': '/api/notifications/send-outreach-summary',
      'price-drop': '/api/notifications/send-price-drop',
      'negotiation-update': '/api/notifications/send-negotiation-update',
    };

    const endpoint = endpoints[action];
    if (!endpoint) {
      return NextResponse.json(
        { success: false, error: `Unknown action: ${action}` },
        { status: 400 },
      );
    }

    const res = await fetch(`${BACKEND_URL}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30_000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('Notifications API error:', error);
    return NextResponse.json(
      { success: false, error: String(error) },
      { status: 500 },
    );
  }
}
