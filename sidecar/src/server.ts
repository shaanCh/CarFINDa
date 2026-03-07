/**
 * Sift Browser Sidecar — HTTP Server
 *
 * Exposes browser control via Playwright behind a Bearer-token–protected
 * Express API. The route surface matches what BrowserControlClient in the
 * backend already calls, so zero backend changes are needed.
 */

import express, { type Request, type Response, type NextFunction } from "express";
import crypto from "crypto";
import {
  listProfiles,
  createProfile,
  getProfile,
  ensureBrowser,
  stopBrowser,
  resetProfile,
  deleteProfile,
  listTabs,
} from "./profiles.js";
import {
  navigate,
  snapshot,
  screenshot,
  content,
  act,
  evaluate,
  openTab,
  focusTab,
  closeTab,
  getCookies,
  setCookies,
  clearCookies,
  getStorage,
  setStorage,
  clearStorage,
} from "./actions.js";

const PORT = parseInt(process.env.PORT || "3000", 10);
const TOKEN = process.env.SIDECAR_TOKEN || process.env.OPENCLAW_GATEWAY_TOKEN || "";
const NODE_ENV = process.env.NODE_ENV || "development";

if (!TOKEN && NODE_ENV === "production") {
  throw new Error(
    "SIDECAR_TOKEN (or OPENCLAW_GATEWAY_TOKEN) is required in production."
  );
}

const app = express();
app.use(express.json());

// ---------------------------------------------------------------------------
// Auth middleware
// ---------------------------------------------------------------------------
function auth(req: Request, res: Response, next: NextFunction): void {
  if (!TOKEN) return next(); // no token configured = open (dev mode)
  const header = req.headers.authorization || "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!bearer) {
    res.status(401).json({ error: "Missing Authorization header" });
    return;
  }
  const a = Buffer.from(bearer);
  const b = Buffer.from(TOKEN);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    res.status(403).json({ error: "Invalid token" });
    return;
  }
  next();
}

app.use(auth);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract profile name from query string (required for most routes). */
function profileParam(req: Request): string {
  const name = (req.query.profile as string) || "";
  if (!name) throw Object.assign(new Error("?profile= query param required"), { status: 400 });
  return name;
}

/** Ensure a profile exists, creating it if necessary (auto-provision). */
function ensureProfile(name: string): void {
  try {
    getProfile(name);
  } catch {
    createProfile(name);
  }
}

/** Wrap an async route handler to catch errors and send JSON responses. */
function wrap(
  fn: (req: Request, res: Response) => Promise<void>
): (req: Request, res: Response, next: NextFunction) => void {
  return (req, res, next) => {
    fn(req, res).catch(next);
  };
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// Health / status
app.get("/", (_req, res) => {
  res.json({ ok: true, service: "sift-browser-sidecar", version: "1.0.0" });
});

// Profiles
app.get("/profiles", wrap(async (_req, res) => {
  res.json({ ok: true, profiles: listProfiles() });
}));

app.post("/profiles/create", wrap(async (req, res) => {
  const name = req.body?.name;
  if (!name) throw Object.assign(new Error("name required"), { status: 400 });
  ensureProfile(name); // idempotent — no 409 if already exists
  res.json({ ok: true, name });
}));

app.delete("/profiles/:name", wrap(async (req, res) => {
  await deleteProfile(req.params.name as string);
  res.json({ ok: true });
}));

// Browser lifecycle
app.post("/start", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  await ensureBrowser(name);
  res.json({ ok: true, profile: name });
}));

app.post("/stop", wrap(async (req, res) => {
  const name = profileParam(req);
  await stopBrowser(name);
  res.json({ ok: true });
}));

app.post("/reset-profile", wrap(async (req, res) => {
  const name = profileParam(req);
  await resetProfile(name);
  res.json({ ok: true });
}));

// Tabs
app.get("/tabs", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const tabs = await listTabs(name);
  res.json({ ok: true, tabs });
}));

app.post("/tabs/open", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const result = await openTab(name, req.body || {});
  res.json(result);
}));

app.post("/tabs/focus", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await focusTab(name, req.body);
  res.json(result);
}));

app.delete("/tabs/:targetId", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await closeTab(name, req.params.targetId as string);
  res.json(result);
}));

// Navigation
app.post("/navigate", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const result = await navigate(name, req.body);
  res.json(result);
}));

// Snapshot (AI-readable page content)
app.get("/snapshot", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const params = { ...req.query } as Record<string, string>;
  delete params.profile;
  delete params.target;
  const result = await snapshot(name, params);
  res.json(result);
}));

// Content (rendered HTML for programmatic scraping)
app.get("/content", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const result = await content(name);
  res.json(result);
}));

// Screenshot
app.post("/screenshot", wrap(async (req, res) => {
  const name = profileParam(req);
  ensureProfile(name);
  const result = await screenshot(name, req.body || {});
  res.json(result);
}));

// Act (click, type, press, hover, scroll, select)
app.post("/act", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await act(name, req.body);
  res.json(result);
}));

// Evaluate (run JS on page — used by CAPTCHA solver)
app.post("/evaluate", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await evaluate(name, req.body);
  res.json(result);
}));

// Cookies
app.get("/cookies", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await getCookies(name);
  res.json(result);
}));

app.post("/cookies/set", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await setCookies(name, req.body);
  res.json(result);
}));

app.post("/cookies/clear", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await clearCookies(name);
  res.json(result);
}));

// Storage (localStorage / sessionStorage)
app.get("/storage/:kind", wrap(async (req, res) => {
  const name = profileParam(req);
  const key = req.query.key as string | undefined;
  const result = await getStorage(name, req.params.kind as string, key);
  res.json(result);
}));

app.post("/storage/:kind/set", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await setStorage(name, req.params.kind as string, req.body);
  res.json(result);
}));

app.post("/storage/:kind/clear", wrap(async (req, res) => {
  const name = profileParam(req);
  const result = await clearStorage(name, req.params.kind as string);
  res.json(result);
}));

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

// Error handler must be registered after all routes
app.use(((err: Error & { status?: number }, _req: Request, res: Response, _next: NextFunction) => {
  const status = err.status || 500;
  console.error(`[server] ${status} ${err.message}`);
  res.status(status).json({ error: err.message });
}) as express.ErrorRequestHandler);

// Bind to :: (dual-stack) so Fly.io private IPv6 networking works
app.listen(PORT, "::", () => {
  console.log(`[sidecar] Sift Browser Sidecar listening on :${PORT}`);
});
