/**
 * Vincent liveness probe (same-origin, CSP-safe).
 *
 * Vincent is the default LOCAL brain — Vincent OS running on the host at
 * port 20128, OpenAI-compatible, zero-key. The browser must not hit that
 * endpoint directly: the CSP connect-src forbids it, and `localhost` inside
 * the frontend container is the container itself, not the host. So the
 * component fetches this route same-origin and we do the cross-host probe
 * server-side, reaching the host via the container gateway.
 */

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const BRAIN_BASE = 'http://host.containers.internal:20128';
const ENDPOINT = 'http://localhost:20128';
const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, max-age=0',
  Pragma: 'no-cache',
};

async function probe(): Promise<boolean> {
  try {
    const res = await fetch(`${BRAIN_BASE}/v1/models`, {
      signal: AbortSignal.timeout(2000),
    });
    // A 2xx from the OpenAI-compatible models endpoint means the brain is up,
    // even if the model list is empty (Vincent OS serves it zero-key).
    if (res.ok) return true;
  } catch {
    /* fall through to the root probe */
  }
  try {
    const res = await fetch(`${BRAIN_BASE}/`, {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function GET() {
  const connected = await probe();
  return NextResponse.json(
    { connected, model: 'vincent', endpoint: ENDPOINT },
    { headers: NO_STORE_HEADERS },
  );
}
