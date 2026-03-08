/**
 * Profile & Browser Lifecycle Management
 *
 * Each profile gets a persistent Chromium context via Playwright,
 * with cookies/storage persisted to disk across restarts.
 */

import { chromium, type BrowserContext, type Page } from "playwright-core";
import { existsSync, mkdirSync, readdirSync, rmSync } from "fs";
import path from "path";
import { STEALTH_USER_AGENT, STEALTH_ARGS, applyStealthScripts } from "./stealth.js";

const DATA_DIR = process.env.DATA_DIR || "/data";
const PROFILES_DIR = path.join(DATA_DIR, "profiles");
const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export interface ProfileState {
  name: string;
  context: BrowserContext | null;
  launching: Promise<BrowserContext> | null;
  userDataDir: string;
  idleTimer: ReturnType<typeof setTimeout> | null;
}

const profiles = new Map<string, ProfileState>();

function validateName(name: string): void {
  if (!name || name.length > 64 || !/^[a-zA-Z0-9_-]+$/.test(name)) {
    throw new Error(
      "Profile name must be 1-64 chars, alphanumeric/hyphens/underscores"
    );
  }
}

function profileDir(name: string): string {
  return path.join(PROFILES_DIR, name);
}

function buildProfileState(name: string): ProfileState {
  return {
    name,
    context: null,
    launching: null,
    userDataDir: profileDir(name),
    idleTimer: null,
  };
}

function syncProfilesFromDisk(): void {
  if (!existsSync(PROFILES_DIR)) mkdirSync(PROFILES_DIR, { recursive: true });

  const persistedNames = new Set<string>();
  for (const entry of readdirSync(PROFILES_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;

    try {
      validateName(entry.name);
    } catch {
      console.warn(`[profiles] Ignoring invalid persisted profile '${entry.name}'`);
      continue;
    }

    persistedNames.add(entry.name);
    if (!profiles.has(entry.name)) {
      profiles.set(entry.name, buildProfileState(entry.name));
    }
  }

  for (const [name, state] of profiles.entries()) {
    if (persistedNames.has(name)) continue;
    if (state.context || state.launching) continue;
    profiles.delete(name);
  }
}

function resetIdleTimer(state: ProfileState): void {
  if (state.idleTimer) clearTimeout(state.idleTimer);
  state.idleTimer = setTimeout(async () => {
    if (state.context) {
      console.log(`[profiles] Idle timeout, closing browser for ${state.name}`);
      await stopBrowser(state.name);
    }
  }, IDLE_TIMEOUT_MS);
}

export function listProfiles(): { name: string; running: boolean }[] {
  syncProfilesFromDisk();
  return Array.from(profiles.values())
    .map((p) => ({
      name: p.name,
      running: p.context !== null || p.launching !== null,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function createProfile(name: string): ProfileState {
  validateName(name);
  syncProfilesFromDisk();
  const existing = profiles.get(name);
  if (existing) return existing;

  const dir = profileDir(name);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const state = buildProfileState(name);
  profiles.set(name, state);
  return state;
}

export function getProfile(name: string): ProfileState {
  syncProfilesFromDisk();
  const state = profiles.get(name);
  if (!state) {
    throw Object.assign(new Error(`Profile '${name}' not found`), {
      status: 404,
    });
  }
  return state;
}

export async function ensureBrowser(name: string): Promise<BrowserContext> {
  const state = getProfile(name);
  if (state.context) {
    resetIdleTimer(state);
    return state.context;
  }
  if (state.launching) return state.launching;

  state.launching = chromium
    .launchPersistentContext(state.userDataDir, {
      headless: false,
      channel: "chrome",
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-sync",
        ...(process.env.HEADLESS !== "false" ? ["--headless=new"] : []),
        ...STEALTH_ARGS,
      ],
      viewport: { width: 1440, height: 900 },
      userAgent: STEALTH_USER_AGENT,
      locale: "en-US",
      timezoneId: "America/Chicago",
    })
    .then(async (ctx) => {
      await applyStealthScripts(ctx);
      state.context = ctx;
      state.launching = null;
      resetIdleTimer(state);
      console.log(`[profiles] Browser launched for ${name} (stealth enabled)`);
      return ctx;
    })
    .catch((err) => {
      state.launching = null;
      throw err;
    });

  return state.launching;
}

export async function stopBrowser(name: string): Promise<void> {
  const state = getProfile(name);
  if (state.idleTimer) clearTimeout(state.idleTimer);
  state.idleTimer = null;
  if (state.context) {
    await state.context.close().catch(() => {});
    state.context = null;
    console.log(`[profiles] Browser stopped for ${name}`);
  }
}

export async function resetProfile(name: string): Promise<void> {
  const state = createProfile(name);
  await stopBrowser(name);
  if (existsSync(state.userDataDir)) rmSync(state.userDataDir, { recursive: true, force: true });
  mkdirSync(state.userDataDir, { recursive: true });
}

export async function deleteProfile(name: string): Promise<void> {
  const state = getProfile(name);
  await stopBrowser(name).catch(() => {});
  if (existsSync(state.userDataDir)) rmSync(state.userDataDir, { recursive: true, force: true });
  profiles.delete(name);
}

export async function getPage(
  name: string,
  targetId?: string
): Promise<Page> {
  const ctx = await ensureBrowser(name);
  const pages = ctx.pages();

  if (targetId) {
    for (const page of pages) {
      const id = await pageTargetId(page);
      if (id === targetId) return page;
    }
    throw Object.assign(
      new Error(`Tab ${targetId} not found in profile ${name}`),
      { status: 404 }
    );
  }

  // Return the last active page or create one
  if (pages.length === 0) {
    return ctx.newPage();
  }
  return pages[pages.length - 1];
}

export async function listTabs(
  name: string
): Promise<{ targetId: string; url: string; title: string }[]> {
  const ctx = await ensureBrowser(name);
  const results = [];
  for (const page of ctx.pages()) {
    results.push({
      targetId: await pageTargetId(page),
      url: page.url(),
      title: await page.title(),
    });
  }
  return results;
}

async function pageTargetId(page: Page): Promise<string> {
  try {
    const session = await page.context().newCDPSession(page);
    const info = await session.send("Target.getTargetInfo");
    await session.detach();
    return info.targetInfo.targetId;
  } catch {
    // Fallback: use a hash of the page URL + creation order
    return `page-${Buffer.from(page.url()).toString("base64url").slice(0, 12)}`;
  }
}

// Ensure profiles directory exists on startup
if (!existsSync(PROFILES_DIR)) mkdirSync(PROFILES_DIR, { recursive: true });
syncProfilesFromDisk();
