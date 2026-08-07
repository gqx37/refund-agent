/**
 * The only way into the agent.
 *
 * The browser holds no credential; it calls same-origin /api/*, and this handler
 * attaches the shared secret server-side and forwards to Fly. That makes the
 * public Fly URL inert on its own — the demo cannot be scripted around the UI.
 *
 * Two things here are load-bearing and easy to get wrong:
 *
 *  1. The upstream body is handed straight to the Response. Awaiting .text() or
 *     .json() anywhere on this path would buffer the whole SSE stream and the
 *     answer would land in one lump instead of token by token.
 *
 *  2. The real client IP is forwarded explicitly. Every request now reaches Fly
 *     from a Vercel address, so the backend's own Fly-Client-IP is useless for
 *     rate limiting — without this header every visitor would share one token
 *     bucket. The backend only believes the header because the secret above
 *     authenticated this hop.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8080";
const SHARED_SECRET = process.env.PROXY_SHARED_SECRET ?? "";

/** Allowlist, so the proxy exposes the demo's surface and not the whole service. */
const ROUTES: Record<string, { method: "GET" | "POST"; path: string }> = {
  // Wakes a suspended machine while the visitor is still reading the page.
  warm: { method: "GET", path: "/health" },
  stream: { method: "POST", path: "/v1/stream" },
};

function clientIp(req: Request): string {
  const forwarded = req.headers.get("x-forwarded-for")?.split(",")[0].trim();
  return forwarded || req.headers.get("x-real-ip")?.trim() || "";
}

async function proxy(req: Request, segments: string[]): Promise<Response> {
  const route = segments.length === 1 ? ROUTES[segments[0]] : undefined;
  if (!route || route.method !== req.method) {
    return Response.json({ detail: "Not found." }, { status: 404 });
  }

  const headers = new Headers({ Accept: req.headers.get("accept") ?? "*/*" });
  if (SHARED_SECRET) headers.set("Authorization", `Bearer ${SHARED_SECRET}`);
  const ip = clientIp(req);
  if (ip) headers.set("X-Demo-Client-IP", ip);

  let body: string | undefined;
  if (route.method === "POST") {
    body = await req.text();
    headers.set("Content-Type", "application/json");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}${route.path}`, {
      method: route.method,
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: "The agent is unreachable right now. Please try again." },
      { status: 502 },
    );
  }

  // Stream passthrough — no await on the body.
  const out = new Headers({
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    "Cache-Control": "no-store, no-transform",
    "X-Accel-Buffering": "no",
  });
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: Request, { params }: Ctx) {
  return proxy(req, (await params).path);
}

export async function POST(req: Request, { params }: Ctx) {
  return proxy(req, (await params).path);
}
