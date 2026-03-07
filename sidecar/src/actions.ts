/**
 * Page Interaction Handlers
 *
 * Each function maps to an HTTP endpoint and wraps a Playwright API call.
 * Response shapes match what BrowserControlClient in the backend expects.
 */

import type { Page, BrowserContext } from "playwright-core";
import { getPage, getProfile, ensureBrowser, listTabs } from "./profiles.js";
import { writeFileSync } from "fs";
import { tmpdir } from "os";
import path from "path";

// ---------------------------------------------------------------------------
// Navigate
// ---------------------------------------------------------------------------
export async function navigate(
  profile: string,
  body: { url: string; waitUntil?: string }
): Promise<object> {
  const page = await getPage(profile);
  const resp = await page.goto(body.url, {
    waitUntil: (body.waitUntil as "load" | "domcontentloaded" | "networkidle") || "load",
    timeout: 30_000,
  });
  // Auto-include snapshot so agent has fresh page content + refs immediately
  const snap = await takeSnapshot(page);
  return {
    ok: true,
    url: page.url(),
    status: resp?.status() ?? null,
    title: await page.title(),
    snapshot: snap,
  };
}

// ---------------------------------------------------------------------------
// Snapshot (AI-readable page content with element refs)
// ---------------------------------------------------------------------------

/** Playwright exposes _snapshotForAI as a private API on Page. */
interface PageWithSnapshot extends Page {
  _snapshotForAI?: (opts?: { timeout?: number }) => Promise<{ full?: string }>;
}

export async function snapshot(
  profile: string,
  params: Record<string, string>
): Promise<object> {
  const page = await getPage(profile);
  const snap = await takeSnapshot(page);
  return { ok: true, snapshot: snap };
}

// ---------------------------------------------------------------------------
// Screenshot
// ---------------------------------------------------------------------------
export async function screenshot(
  profile: string,
  body: { fullPage?: boolean }
): Promise<object> {
  const page = await getPage(profile);
  const buffer = await page.screenshot({
    fullPage: body?.fullPage ?? false,
    type: "png",
  });

  // Save to temp file for path-based access
  const filename = `screenshot-${Date.now()}.png`;
  const filepath = path.join(tmpdir(), filename);
  writeFileSync(filepath, buffer);

  return {
    ok: true,
    path: filepath,
    base64: buffer.toString("base64"),
    mimeType: "image/png",
    url: page.url(),
  };
}

// ---------------------------------------------------------------------------
// Act (click, type, press, hover, scroll, select)
// ---------------------------------------------------------------------------
export async function act(
  profile: string,
  body: {
    kind: string;
    ref?: string;
    text?: string;
    key?: string;
    direction?: string;
    values?: string[];
  }
): Promise<object> {
  const page = await getPage(profile);
  const { kind, ref, text, key, direction, values } = body;

  switch (kind) {
    case "click": {
      if (!ref) throw Object.assign(new Error("ref required for click"), { status: 400 });
      await refLocator(page, ref).click({ timeout: 10_000 });
      await waitForPageSettle(page);
      break;
    }
    case "type": {
      if (!ref) throw Object.assign(new Error("ref required for type"), { status: 400 });
      if (!text) throw Object.assign(new Error("text required for type"), { status: 400 });
      await refLocator(page, ref).fill(text, { timeout: 10_000 });
      break;
    }
    case "press": {
      if (!key) throw Object.assign(new Error("key required for press"), { status: 400 });
      await page.keyboard.press(key);
      if (key === "Enter") await waitForPageSettle(page);
      break;
    }
    case "hover": {
      if (!ref) throw Object.assign(new Error("ref required for hover"), { status: 400 });
      await refLocator(page, ref).hover({ timeout: 10_000 });
      break;
    }
    case "scroll": {
      const delta = direction === "up" ? -500 : 500;
      await page.mouse.wheel(0, delta);
      break;
    }
    case "select": {
      if (!ref) throw Object.assign(new Error("ref required for select"), { status: 400 });
      await refLocator(page, ref).selectOption(values || [], { timeout: 10_000 });
      await waitForPageSettle(page);
      break;
    }
    default:
      throw Object.assign(new Error(`Unknown action kind: ${kind}`), { status: 400 });
  }

  // Auto-include snapshot so agent has fresh refs after every action
  const snap = await takeSnapshot(page);
  return { ok: true, kind, snapshot: snap };
}

/**
 * Resolve an element ref (e.g. "e3") from a previous _snapshotForAI to a
 * Playwright locator. Uses the `aria-ref=` selector engine (no `internal:` prefix).
 */
function refLocator(page: Page, ref: string) {
  const normalized = ref.startsWith("e") ? ref : ref.replace(/^[@]|^ref=/, "");
  return page.locator(`aria-ref=${normalized}`);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
export async function openTab(
  profile: string,
  body: { url?: string }
): Promise<object> {
  const ctx = await ensureBrowser(profile);
  const page = await ctx.newPage();
  if (body?.url) await page.goto(body.url, { timeout: 20_000 });
  const targetId = await getTargetId(page);
  return { ok: true, targetId, url: page.url() };
}

export async function focusTab(
  profile: string,
  body: { targetId: string }
): Promise<object> {
  const page = await getPage(profile, body.targetId);
  await page.bringToFront();
  return { ok: true, targetId: body.targetId };
}

export async function closeTab(
  profile: string,
  targetId: string
): Promise<object> {
  const page = await getPage(profile, targetId);
  await page.close();
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Content (rendered HTML — used by programmatic scrapers)
// ---------------------------------------------------------------------------
export async function content(profile: string): Promise<object> {
  const page = await getPage(profile);
  const html = await page.content();
  return { ok: true, html, url: page.url() };
}

// ---------------------------------------------------------------------------
// Evaluate (run JS on the page — used by CAPTCHA solver)
// ---------------------------------------------------------------------------
export async function evaluate(
  profile: string,
  body: { script: string; args?: unknown[] }
): Promise<object> {
  const page = await getPage(profile);
  // The script should be a function expression, e.g. "() => document.title"
  // eslint-disable-next-line no-eval
  const fn = new Function(`return (${body.script})`)();
  const args = body.args || [];
  // page.evaluate takes a single arg — pass first element or undefined
  const result = await page.evaluate(fn, args.length === 1 ? args[0] : args.length > 1 ? args : undefined);
  return { ok: true, result };
}

// ---------------------------------------------------------------------------
// Cookies
// ---------------------------------------------------------------------------
export async function getCookies(profile: string): Promise<object> {
  const ctx = await ensureBrowser(profile);
  const cookies = await ctx.cookies();
  return { ok: true, cookies };
}

export async function setCookies(
  profile: string,
  body: { cookie?: object; cookies?: object[] }
): Promise<object> {
  const ctx = await ensureBrowser(profile);
  const items = body.cookies || (body.cookie ? [body.cookie] : []);
  await ctx.addCookies(items as Parameters<BrowserContext["addCookies"]>[0]);
  return { ok: true };
}

export async function clearCookies(profile: string): Promise<object> {
  const ctx = await ensureBrowser(profile);
  await ctx.clearCookies();
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Storage (localStorage / sessionStorage)
// ---------------------------------------------------------------------------
export async function getStorage(
  profile: string,
  kind: string,
  key?: string
): Promise<object> {
  const page = await getPage(profile);
  const storage = kind === "local" ? "localStorage" : "sessionStorage";
  const data = await page.evaluate(
    ([s, k]) => {
      const store = s === "localStorage" ? localStorage : sessionStorage;
      if (k) return store.getItem(k);
      const result: Record<string, string | null> = {};
      for (let i = 0; i < store.length; i++) {
        const key = store.key(i);
        if (key) result[key] = store.getItem(key);
      }
      return result;
    },
    [storage, key || ""] as const
  );
  return { ok: true, data };
}

export async function setStorage(
  profile: string,
  kind: string,
  body: { key: string; value: string }
): Promise<object> {
  const page = await getPage(profile);
  const storage = kind === "local" ? "localStorage" : "sessionStorage";
  await page.evaluate(
    ([s, k, v]) => {
      const store = s === "localStorage" ? localStorage : sessionStorage;
      store.setItem(k, v);
    },
    [storage, body.key, body.value] as const
  );
  return { ok: true };
}

export async function clearStorage(
  profile: string,
  kind: string
): Promise<object> {
  const page = await getPage(profile);
  const storage = kind === "local" ? "localStorage" : "sessionStorage";
  await page.evaluate((s) => {
    const store = s === "localStorage" ? localStorage : sessionStorage;
    store.clear();
  }, storage);
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * After click/select/Enter, wait briefly for SPAs to load new content.
 * Uses networkidle (no requests for 500ms) with a short timeout so we
 * don't block forever on pages with long-polling or websockets.
 */
async function waitForPageSettle(page: Page): Promise<void> {
  await page
    .waitForLoadState("networkidle", { timeout: 3000 })
    .catch(() => {});
}

/**
 * Take an AI-readable snapshot of the page. Used by the snapshot endpoint
 * and auto-included in navigate/act responses so the agent always has
 * fresh refs without a separate round-trip.
 */
async function takeSnapshot(page: Page): Promise<string> {
  const maybe = page as PageWithSnapshot;
  if (maybe._snapshotForAI) {
    try {
      const result = await maybe._snapshotForAI({ timeout: 5000 });
      return String(result?.full ?? "");
    } catch {
      return "";
    }
  }
  // Fallback: public ariaSnapshot
  try {
    return await page.locator("body").ariaSnapshot();
  } catch {
    return await page.innerText("body").catch(() => "");
  }
}

async function getTargetId(page: Page): Promise<string> {
  try {
    const session = await page.context().newCDPSession(page);
    const info = await session.send("Target.getTargetInfo");
    await session.detach();
    return info.targetInfo.targetId;
  } catch {
    return `page-${Date.now()}`;
  }
}
