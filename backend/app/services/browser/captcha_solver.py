"""
CAPTCHA Solver Service

Detects CAPTCHA type on a page and solves it via an external service
(CapSolver or 2Captcha). Used as a fallback when stealth measures
don't prevent CAPTCHAs from appearing.

Flow:
  1. Run JS on the page to detect CAPTCHA type + extract sitekey
  2. Submit to solving service API
  3. Poll for solution token
  4. Inject token into the page's callback
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# JS that finds the CAPTCHA type and sitekey on the current page
_DETECT_CAPTCHA_JS = """
() => {
  const result = { type: null, sitekey: null, action: null, enterprise: false };

  // reCAPTCHA v2 / v3
  const recapEl = document.querySelector('[data-sitekey]');
  if (recapEl) {
    result.sitekey = recapEl.getAttribute('data-sitekey');
    result.action = recapEl.getAttribute('data-action') || null;
    const isV3 = recapEl.getAttribute('data-size') === 'invisible'
      || document.querySelector('.grecaptcha-badge') !== null;
    result.type = isV3 ? 'recaptchav3' : 'recaptchav2';
    return result;
  }

  // reCAPTCHA via script tag
  const recapScript = document.querySelector(
    'script[src*="recaptcha"], script[src*="grecaptcha"]'
  );
  if (recapScript) {
    const src = recapScript.getAttribute('src') || '';
    const match = src.match(/[?&]render=([^&]+)/);
    if (match && match[1] !== 'explicit') {
      result.type = 'recaptchav3';
      result.sitekey = match[1];
      return result;
    }
  }

  // reCAPTCHA Enterprise
  const enterpriseScript = document.querySelector(
    'script[src*="recaptcha/enterprise"]'
  );
  if (enterpriseScript) {
    result.enterprise = true;
    const el = document.querySelector('[data-sitekey]');
    if (el) {
      result.sitekey = el.getAttribute('data-sitekey');
      result.type = 'recaptchav2';
      return result;
    }
  }

  // hCaptcha
  const hcapEl = document.querySelector('[data-hcaptcha-sitekey], .h-captcha[data-sitekey]');
  if (hcapEl) {
    result.type = 'hcaptcha';
    result.sitekey = hcapEl.getAttribute('data-sitekey')
      || hcapEl.getAttribute('data-hcaptcha-sitekey');
    return result;
  }
  const hcapIframe = document.querySelector('iframe[src*="hcaptcha.com"]');
  if (hcapIframe) {
    result.type = 'hcaptcha';
    const src = hcapIframe.getAttribute('src') || '';
    const match = src.match(/sitekey=([^&]+)/);
    if (match) result.sitekey = match[1];
    return result;
  }

  // Cloudflare Turnstile
  const cfEl = document.querySelector('.cf-turnstile[data-sitekey]');
  if (cfEl) {
    result.type = 'turnstile';
    result.sitekey = cfEl.getAttribute('data-sitekey');
    return result;
  }
  const cfIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
  if (cfIframe) {
    result.type = 'turnstile';
    const src = cfIframe.getAttribute('src') || '';
    const match = src.match(/sitekey=([^&]+)/);
    if (match) result.sitekey = match[1];
    return result;
  }

  // DataDome
  const ddIframe = document.querySelector('iframe[src*="captcha-delivery.com"]');
  if (ddIframe) {
    result.type = 'datadome';
    // DataDome embeds the captcha in an iframe; sitekey is in the dd config
    const ddScript = document.querySelector('script[data-cfasync]');
    if (ddScript) {
      try {
        const text = ddScript.textContent || '';
        const match = text.match(/cid['"\\s:]+['"]([^'"]+)['"]/);
        if (match) result.sitekey = match[1];
      } catch(e) {}
    }
    return result;
  }

  return result;
}
"""

# JS to inject a solved CAPTCHA token into the page
_INJECT_TOKEN_JS = """
(type, token) => {
  if (type === 'recaptchav2' || type === 'recaptchav3') {
    const textarea = document.querySelector('#g-recaptcha-response')
      || document.querySelector('[name="g-recaptcha-response"]');
    if (textarea) {
      textarea.value = token;
      textarea.style.display = 'none';
    }
    document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {
      el.value = token;
    });
    if (typeof window.___grecaptcha_cfg !== 'undefined') {
      try {
        const clients = window.___grecaptcha_cfg.clients;
        for (const key in clients) {
          const client = clients[key];
          const walk = (obj) => {
            for (const k in obj) {
              if (typeof obj[k] === 'function' && k.length === 2) {
                try { obj[k](token); } catch(e) {}
              }
              if (typeof obj[k] === 'object' && obj[k] !== null) walk(obj[k]);
            }
          };
          walk(client);
        }
      } catch(e) {}
    }
    return true;
  }

  if (type === 'hcaptcha') {
    const textarea = document.querySelector('[name="h-captcha-response"]')
      || document.querySelector('[name="g-recaptcha-response"]');
    if (textarea) textarea.value = token;
    if (typeof window.hcaptcha !== 'undefined') {
      try { window.hcaptcha.execute(); } catch(e) {}
    }
    return true;
  }

  if (type === 'turnstile') {
    const input = document.querySelector('[name="cf-turnstile-response"]');
    if (input) input.value = token;
    return true;
  }

  if (type === 'datadome') {
    // DataDome typically auto-redirects after the cookie is set
    // The token is a cookie value; inject it and reload
    if (token) {
      document.cookie = 'datadome=' + token + '; path=/; secure; SameSite=Lax';
      window.location.reload();
    }
    return true;
  }

  return false;
}
"""


class CaptchaSolver:
    """Solves CAPTCHAs via CapSolver or 2Captcha API."""

    def __init__(self, provider: str, api_key: str, timeout: int = 120):
        self._provider = provider
        self._api_key = api_key
        self._timeout = timeout

    async def detect_and_solve(
        self,
        page_url: str,
        evaluate_js: Any,
    ) -> Optional[str]:
        """
        Detect CAPTCHA on page and attempt to solve it.

        Args:
            page_url: Current page URL (needed by solving APIs).
            evaluate_js: Async callable that runs JS on the page.
                         Signature: evaluate_js(script, *args) -> result

        Returns:
            Solved token string, or None if no CAPTCHA or solve failed.
        """
        info = await evaluate_js(_DETECT_CAPTCHA_JS)
        if not info or not info.get("type"):
            logger.debug("[CaptchaSolver] No solvable CAPTCHA detected on page")
            return None

        captcha_type = info["type"]
        sitekey = info.get("sitekey")

        logger.info(
            "[CaptchaSolver] Detected %s (sitekey=%s..., enterprise=%s)",
            captcha_type,
            (sitekey or "")[:12],
            info.get("enterprise", False),
        )

        # DataDome uses a different solve flow
        if captcha_type == "datadome":
            return await self._solve_datadome(page_url, info)

        if not sitekey:
            logger.warning("[CaptchaSolver] No sitekey found, cannot solve")
            return None

        token = await self._request_solution(
            captcha_type=captcha_type,
            sitekey=sitekey,
            page_url=page_url,
            action=info.get("action"),
            enterprise=info.get("enterprise", False),
        )

        if not token:
            return None

        try:
            await evaluate_js(_INJECT_TOKEN_JS, captcha_type, token)
            logger.info("[CaptchaSolver] Token injected for %s", captcha_type)
        except Exception as e:
            logger.warning("[CaptchaSolver] Token injection failed: %s", e)

        return token

    async def _solve_datadome(
        self, page_url: str, info: dict
    ) -> Optional[str]:
        """Solve DataDome captcha via CapSolver's AntiDataDome task."""
        if self._provider != "capsolver":
            logger.warning("[CaptchaSolver] DataDome solving only supported with CapSolver")
            return None

        captcha_url = info.get("sitekey", "")
        # If sitekey is already a full URL, use it; otherwise build it
        if captcha_url.startswith("https://"):
            full_captcha_url = captcha_url
        else:
            full_captcha_url = f"https://geo.captcha-delivery.com/captcha/?initialCid={captcha_url}"

        task: Dict[str, Any] = {
            "type": "DatadomeSliderTask",
            "websiteURL": page_url,
            "captchaUrl": full_captcha_url,
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        # DatadomeSliderTask requires a proxy — log if none configured
        logger.info("[CaptchaSolver] DataDome requires proxy for CapSolver — task may fail without one")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.capsolver.com/createTask",
                json={"clientKey": self._api_key, "task": task},
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                logger.error(
                    "[CaptchaSolver] CapSolver DataDome create failed: %s",
                    data.get("errorDescription"),
                )
                return None

            task_id = data.get("taskId")
            if not task_id:
                solution = data.get("solution", {})
                return solution.get("cookie") or self._extract_token(solution, "datadome")

            return await self._poll_capsolver(client, task_id)

    async def _request_solution(
        self,
        captcha_type: str,
        sitekey: str,
        page_url: str,
        action: Optional[str] = None,
        enterprise: bool = False,
    ) -> Optional[str]:
        if self._provider == "capsolver":
            return await self._solve_capsolver(
                captcha_type, sitekey, page_url, action, enterprise
            )
        elif self._provider == "2captcha":
            return await self._solve_2captcha(
                captcha_type, sitekey, page_url, action, enterprise
            )
        else:
            logger.error("[CaptchaSolver] Unknown provider: %s", self._provider)
            return None

    # ------------------------------------------------------------------
    # CapSolver
    # ------------------------------------------------------------------

    async def _solve_capsolver(
        self,
        captcha_type: str,
        sitekey: str,
        page_url: str,
        action: Optional[str],
        enterprise: bool,
    ) -> Optional[str]:
        task = self._build_capsolver_task(
            captcha_type, sitekey, page_url, action, enterprise
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.capsolver.com/createTask",
                json={"clientKey": self._api_key, "task": task},
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                logger.error(
                    "[CaptchaSolver] CapSolver create failed: %s",
                    data.get("errorDescription"),
                )
                return None

            task_id = data.get("taskId")
            if not task_id:
                solution = data.get("solution", {})
                return self._extract_token(solution, captcha_type)

            return await self._poll_capsolver(client, task_id)

    def _build_capsolver_task(
        self,
        captcha_type: str,
        sitekey: str,
        page_url: str,
        action: Optional[str],
        enterprise: bool,
    ) -> Dict[str, Any]:
        if captcha_type == "recaptchav2":
            task_type = (
                "ReCaptchaV2EnterpriseTaskProxyLess"
                if enterprise
                else "ReCaptchaV2TaskProxyLess"
            )
            task: Dict[str, Any] = {
                "type": task_type,
                "websiteURL": page_url,
                "websiteKey": sitekey,
            }
        elif captcha_type == "recaptchav3":
            task_type = (
                "ReCaptchaV3EnterpriseTaskProxyLess"
                if enterprise
                else "ReCaptchaV3TaskProxyLess"
            )
            task = {
                "type": task_type,
                "websiteURL": page_url,
                "websiteKey": sitekey,
                "pageAction": action or "verify",
            }
        elif captcha_type == "hcaptcha":
            task = {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            }
        elif captcha_type == "turnstile":
            task = {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            }
        else:
            task = {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            }
        return task

    async def _poll_capsolver(
        self, client: httpx.AsyncClient, task_id: str
    ) -> Optional[str]:
        elapsed = 0
        interval = 3
        while elapsed < self._timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            resp = await client.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": self._api_key, "taskId": task_id},
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                logger.error(
                    "[CaptchaSolver] CapSolver poll error: %s",
                    data.get("errorDescription"),
                )
                return None

            status = data.get("status")
            if status == "ready":
                solution = data.get("solution", {})
                token = solution.get("cookie") or self._extract_token(solution, None)
                logger.info("[CaptchaSolver] CapSolver solved in %ds", elapsed)
                return token

        logger.warning("[CaptchaSolver] CapSolver timeout after %ds", elapsed)
        return None

    # ------------------------------------------------------------------
    # 2Captcha
    # ------------------------------------------------------------------

    async def _solve_2captcha(
        self,
        captcha_type: str,
        sitekey: str,
        page_url: str,
        action: Optional[str],
        enterprise: bool,
    ) -> Optional[str]:
        params = self._build_2captcha_params(
            captcha_type, sitekey, page_url, action, enterprise
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://2captcha.com/in.php", data=params)
            text = resp.text
            if not text.startswith("OK|"):
                logger.error("[CaptchaSolver] 2Captcha submit failed: %s", text)
                return None

            captcha_id = text.split("|")[1]
            return await self._poll_2captcha(client, captcha_id)

    def _build_2captcha_params(
        self,
        captcha_type: str,
        sitekey: str,
        page_url: str,
        action: Optional[str],
        enterprise: bool,
    ) -> Dict[str, str]:
        params: Dict[str, str] = {
            "key": self._api_key,
            "pageurl": page_url,
            "json": "0",
        }

        if captcha_type in ("recaptchav2", "recaptchav3"):
            params["method"] = "userrecaptcha"
            params["googlekey"] = sitekey
            if captcha_type == "recaptchav3":
                params["version"] = "v3"
                params["action"] = action or "verify"
                params["min_score"] = "0.5"
            if enterprise:
                params["enterprise"] = "1"
        elif captcha_type == "hcaptcha":
            params["method"] = "hcaptcha"
            params["sitekey"] = sitekey
        elif captcha_type == "turnstile":
            params["method"] = "turnstile"
            params["sitekey"] = sitekey
        else:
            params["method"] = "userrecaptcha"
            params["googlekey"] = sitekey

        return params

    async def _poll_2captcha(
        self, client: httpx.AsyncClient, captcha_id: str
    ) -> Optional[str]:
        elapsed = 0
        interval = 5
        while elapsed < self._timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            resp = await client.get(
                "https://2captcha.com/res.php",
                params={
                    "key": self._api_key,
                    "action": "get",
                    "id": captcha_id,
                    "json": "0",
                },
            )
            text = resp.text

            if text == "CAPCHA_NOT_READY":
                continue
            if text.startswith("OK|"):
                token = text.split("|", 1)[1]
                logger.info("[CaptchaSolver] 2Captcha solved in %ds", elapsed)
                return token

            logger.error("[CaptchaSolver] 2Captcha poll error: %s", text)
            return None

        logger.warning("[CaptchaSolver] 2Captcha timeout after %ds", elapsed)
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_token(
        solution: Dict[str, Any], captcha_type: Optional[str]
    ) -> Optional[str]:
        return (
            solution.get("gRecaptchaResponse")
            or solution.get("token")
            or solution.get("text")
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_solver_instance: Optional[CaptchaSolver] = None


def get_captcha_solver() -> Optional[CaptchaSolver]:
    """Return a CaptchaSolver if configured, else None."""
    global _solver_instance
    if _solver_instance is not None:
        return _solver_instance

    from app.config import get_settings

    settings = get_settings()
    if not settings.CAPTCHA_SOLVER_API_KEY:
        return None

    _solver_instance = CaptchaSolver(
        provider=settings.CAPTCHA_SOLVER_PROVIDER,
        api_key=settings.CAPTCHA_SOLVER_API_KEY,
        timeout=settings.CAPTCHA_SOLVER_TIMEOUT_SECONDS,
    )
    return _solver_instance
