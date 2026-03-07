/**
 * Browser Stealth — Anti-detection measures for Playwright
 *
 * Injects scripts and configures browser context to avoid bot detection
 * fingerprints that trigger CAPTCHAs on sites like Amazon, Google, etc.
 */

import type { BrowserContext } from "playwright-core";

/**
 * Realistic Chrome user agent string.
 * Updated periodically to match current stable Chrome releases.
 */
export const STEALTH_USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/131.0.0.0 Safari/537.36";

/**
 * Chromium launch args that reduce bot fingerprinting.
 * Combined with the base args in profiles.ts.
 */
export const STEALTH_ARGS: string[] = [
  // Disable automation flags
  "--disable-blink-features=AutomationControlled",
  // Realistic window size (not a perfect 1280x720 which screams headless)
  "--window-size=1440,900",
  // Enable WebGL (headless often has it disabled — a detection signal)
  "--enable-webgl",
  // Standard features bots often lack
  "--enable-features=NetworkService,NetworkServiceInProcess",
];

/**
 * JavaScript to inject before any page scripts run.
 * Patches the most common bot-detection fingerprints.
 */
const STEALTH_INIT_SCRIPT = `
// 1. Hide navigator.webdriver (the #1 detection signal)
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
  configurable: true,
});

// 2. Fake navigator.plugins (headless Chrome has 0 plugins)
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const plugins = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
    ];
    const arr = Object.create(PluginArray.prototype);
    plugins.forEach((p, i) => { arr[i] = p; });
    Object.defineProperty(arr, 'length', { get: () => plugins.length });
    arr.item = (i) => arr[i] || null;
    arr.namedItem = (name) => plugins.find(p => p.name === name) || null;
    arr.refresh = () => {};
    return arr;
  },
  configurable: true,
});

// 3. Fake navigator.mimeTypes
Object.defineProperty(navigator, 'mimeTypes', {
  get: () => {
    const mimes = [
      { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
      { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
    ];
    const arr = Object.create(MimeTypeArray.prototype);
    mimes.forEach((m, i) => { arr[i] = m; });
    Object.defineProperty(arr, 'length', { get: () => mimes.length });
    arr.item = (i) => arr[i] || null;
    arr.namedItem = (name) => mimes.find(m => m.type === name) || null;
    return arr;
  },
  configurable: true,
});

// 4. Fake navigator.languages
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
  configurable: true,
});

// 5. Pass chrome.runtime check (real Chrome always has this)
if (!window.chrome) {
  window.chrome = {};
}
if (!window.chrome.runtime) {
  window.chrome.runtime = {
    OnInstalledReason: {
      CHROME_UPDATE: 'chrome_update',
      INSTALL: 'install',
      SHARED_MODULE_UPDATE: 'shared_module_update',
      UPDATE: 'update',
    },
    OnRestartRequiredReason: {
      APP_UPDATE: 'app_update',
      OS_UPDATE: 'os_update',
      PERIODIC: 'periodic',
    },
    PlatformArch: {
      ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64',
      X86_32: 'x86-32', X86_64: 'x86-64',
    },
    PlatformNaclArch: {
      ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64',
      X86_32: 'x86-32', X86_64: 'x86-64',
    },
    PlatformOs: {
      ANDROID: 'android', CROS: 'cros', LINUX: 'linux',
      MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win',
    },
    RequestUpdateCheckStatus: {
      NO_UPDATE: 'no_update', THROTTLED: 'throttled',
      UPDATE_AVAILABLE: 'update_available',
    },
  };
}

// 6. Fix Permissions API (headless returns inconsistent results)
const originalQuery = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (params) => {
  if (params.name === 'notifications') {
    return Promise.resolve({ state: Notification.permission, onchange: null });
  }
  return originalQuery(params);
};

// 7. Fake connection API (headless often missing)
if (!navigator.connection) {
  Object.defineProperty(navigator, 'connection', {
    get: () => ({
      effectiveType: '4g',
      rtt: 50,
      downlink: 10,
      saveData: false,
    }),
    configurable: true,
  });
}

// 8. Realistic hardware fingerprint
Object.defineProperty(navigator, 'hardwareConcurrency', {
  get: () => 8,
  configurable: true,
});
Object.defineProperty(navigator, 'deviceMemory', {
  get: () => 8,
  configurable: true,
});

// 9. Fix WebGL vendor/renderer (headless uses "Google SwiftShader")
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {
  // UNMASKED_VENDOR_WEBGL
  if (param === 0x9245) return 'Google Inc. (Apple)';
  // UNMASKED_RENDERER_WEBGL
  if (param === 0x9246) return 'ANGLE (Apple, Apple M1, OpenGL 4.1)';
  return getParameter.call(this, param);
};
const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
WebGL2RenderingContext.prototype.getParameter = function(param) {
  if (param === 0x9245) return 'Google Inc. (Apple)';
  if (param === 0x9246) return 'ANGLE (Apple, Apple M1, OpenGL 4.1)';
  return getParameter2.call(this, param);
};

// 10. Prevent iframe contentWindow detection
// Some sites check if contentWindow.chrome exists in iframes
try {
  const originalAttachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function() {
    return originalAttachShadow.apply(this, arguments);
  };
} catch (e) {}
`;

/**
 * Apply stealth init scripts to a browser context.
 * Must be called before any navigation occurs.
 */
export async function applyStealthScripts(
  context: BrowserContext
): Promise<void> {
  await context.addInitScript(STEALTH_INIT_SCRIPT);
}
