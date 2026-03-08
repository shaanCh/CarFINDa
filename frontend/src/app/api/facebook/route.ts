/**
 * Facebook Marketplace API proxy routes.
 *
 * Proxies frontend requests to the FastAPI backend's negotiate endpoints
 * for Facebook search, login, and DM operations.
 */

import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

/** POST /api/facebook — dispatch { action, ...payload } */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { action, ...payload } = body;

    const routes: Record<string, { path: string; method: string }> = {
      search:       { path: '/api/negotiate/facebook/search', method: 'POST' },
      'login':      { path: '/api/negotiate/login',           method: 'POST' },
      '2fa':        { path: '/api/negotiate/login/2fa',       method: 'POST' },
      'send-dm':    { path: '/api/negotiate/send-dm',         method: 'POST' },
      'preview-dm': { path: '/api/negotiate/send-dm',         method: 'POST' },
    };

    const route = routes[action];
    if (!route) {
      return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }

    // For preview, force send=false
    if (action === 'preview-dm') {
      payload.send = false;
    }

    console.log(`[facebook-proxy] ${action} -> ${route.path}`);

    // Use AbortController for a 3-minute timeout (search can be slow)
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180_000);

    try {
      const backendRes = await fetch(`${BACKEND_URL}${route.path}`, {
        method: route.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      clearTimeout(timeout);

      if (!backendRes.ok) {
        const errorText = await backendRes.text();
        console.error(`Backend ${action} error:`, backendRes.status, errorText);
        return NextResponse.json(
          { error: `Backend error: ${errorText}` },
          { status: backendRes.status },
        );
      }

      const data = await backendRes.json();
      console.log(`[facebook-proxy] ${action} completed`);
      return NextResponse.json(data);
    } finally {
      clearTimeout(timeout);
    }
  } catch (error) {
    console.error('Facebook API proxy error:', error);
    const message = error instanceof Error ? error.message : 'Request failed';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/** GET /api/facebook — login status check */
export async function GET() {
  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/negotiate/login/status`, {
      headers: { 'Content-Type': 'application/json' },
    });

    if (!backendRes.ok) {
      return NextResponse.json({ success: false, status: 'unknown' }, { status: 200 });
    }

    const data = await backendRes.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ success: false, status: 'backend_unreachable' }, { status: 200 });
  }
}
