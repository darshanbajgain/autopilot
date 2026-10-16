"""Website automation with Playwright: connect or launch, log in, find the
site's pages, visit them, run steps and browse like a person."""
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PWTimeout

from .desktop import MAC, WindowSpec, browser_key

# Where the page's top-left corner is on the screen, in CSS pixels.
ORIGIN_JS = """
() => {
  const border = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
  const top = Math.max(0, window.outerHeight - window.innerHeight - border);
  return { x: window.screenX + border, y: window.screenY + top, dpr: window.devicePixelRatio,
           w: window.innerWidth, h: window.innerHeight };
}
"""

# One smooth scroll step on the page's main scroll container (the window or
# an inner panel).
SCROLL_JS = """
({ step, to }) => {
  const ok = e => e && e.isConnected && e.scrollHeight > e.clientHeight + 40;
  let box = window.__apScroller;
  if (!ok(box)) {
    const all = [document.scrollingElement, ...document.querySelectorAll('*')];
    const list = all.filter(e => {
      if (!ok(e)) return false;
      if (e === document.scrollingElement) return true;
      const oy = getComputedStyle(e).overflowY;
      return (oy === 'auto' || oy === 'scroll') && e.clientHeight > 150;
    });
    list.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight);
    box = window.__apScroller = list[0] || null;
  }
  if (!box) return { scrolls: false, atEnd: true };
  const max = box.scrollHeight - box.clientHeight;
  let target = box.scrollTop + step;
  if (to === 'top') target = 0;
  if (to === 'bottom') target = max;
  target = Math.min(max, Math.max(0, target));
  box.scrollTo({ top: target, behavior: 'smooth' });
  return { scrolls: true, atEnd: step >= 0 ? target >= max - 2 : target <= 0 };
}
"""

# Finds the site's navigation links (sidebar / top menu).
DISCOVER_JS = """
({ areaSel, skip }) => {
  const areas = areaSel === 'auto'
    ? ['aside', 'nav', '[role=navigation]', '[class*="sidebar" i]', '[class*="sidenav" i]',
       '[class*="side-nav" i]', '[class*="menu" i]', 'header']
    : [areaSel];
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = e => ((e.innerText || '').trim() || e.getAttribute('aria-label') || e.getAttribute('title') || '')
    .split('\\n').map(s => s.trim()).filter(Boolean).join(' ');
  const skipped = t => skip.some(s => t.toLowerCase().includes(s));
  const clickables = 'a[href], button, [role=link], [role=menuitem], [role=tab], [onclick]';
  for (const sel of areas) {
    let nodes = [];
    try { nodes = [...document.querySelectorAll(sel)]; } catch (e) { return { error: 'bad nav_area selector' }; }
    for (const area of nodes) {
      if (!vis(area)) continue;
      const out = [], seen = new Set();
      let items = [...area.querySelectorAll(clickables)].filter(vis);
      if (items.length < 2) items = [...area.querySelectorAll('li, [class*="item" i]')].filter(vis);
      for (const el of items) {
        const t = label(el);
        if (!t || t.length > 40 || seen.has(t) || skipped(t)) continue;
        seen.add(t);
        const a = el.closest('a[href]') || el.querySelector('a[href]');
        out.push({ label: t, href: a ? a.href : null });
      }
      if (out.length >= 2) return { area: sel, items: out.slice(0, 25) };
    }
  }
  // Fallback: same-site links anywhere on the page.
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    if (!vis(a) || a.origin !== location.origin) continue;
    const t = label(a);
    if (!t || t.length > 40 || seen.has(t) || skipped(t) || a.href === location.href) continue;
    seen.add(t);
    out.push({ label: t, href: a.href });
  }
  return { area: null, items: out.slice(0, 15) };
}
"""

EMAIL_SELECTORS = ('input[type="email"], input[autocomplete="username"], input[autocomplete="email"], '
                   'input[name*="email" i], input[id*="email" i], input[placeholder*="email" i], '
                   'input[name*="user" i], input[id*="user" i], input[placeholder*="user" i], '
                   'input[name*="login" i], input[id*="login" i]')
PASSWORD_SELECTORS = 'input[type="password"]'
SUBMIT_RE = re.compile(r"^\s*(log\s*in|sign\s*in|login|signin|continue|submit|next|enter)\b", re.I)
TYPEABLE = ('textarea, [contenteditable="true"], [contenteditable=""], [role="textbox"], '
            'input[type="text"], input[type="search"], input:not([type])')

SELECTOR_PREFIXES = ("css=", "xpath=", "text=", "id=", "role=", "data-testid=", "#", "[", "//", "internal:")


def looks_like_selector(target):
    t = target.strip()
    return t.startswith(SELECTOR_PREFIXES) or ">>" in t or (t.startswith(".") and " " not in t and len(t) > 1)


class PageRef:
    def __init__(self, label, url=None, direct=False):
        self.label = label
        self.url = url
        self.direct = direct      # an address from the settings: go straight there

    def __repr__(self):
        return self.label


class StepFailed(Exception):
    pass


class Browser:
    def __init__(self, cfg, ctx):
        self.cfg = cfg            # the 'browser' section
        self.ctx = ctx            # shared run context (tuning, human, desktop, log, ...)
        self.page = None
        self.browser = None
        self.nav_area = None
        self.errors = []
        self.visit_count = {}

    # ---- start / stop ------------------------------------------------------

    def start(self, p, endpoint_finder):
        c = self.cfg
        slow = 60
        if c["attach"]:
            endpoint = endpoint_finder()
            self.ctx.log(f"Connecting to your open browser ({endpoint}).")
            self.ctx.log("  -> If the browser asks to allow remote debugging, click 'Allow'.")
            try:
                self.browser = p.chromium.connect_over_cdp(endpoint, slow_mo=slow, timeout=60000)
            except Exception:
                fallback = "http://127.0.0.1:9222"
                try:
                    if endpoint == fallback:
                        raise
                    self.browser = p.chromium.connect_over_cdp(fallback, slow_mo=slow, timeout=15000)
                except Exception:
                    raise RuntimeError(
                        "couldn't connect to your open browser. Turn on chrome://inspect/#remote-debugging "
                        "and click 'Allow' when Chrome asks, or start it with --remote-debugging-port=9222 "
                        "(README section 6). Or set 'attach: no'.")
            context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        else:
            kwargs = dict(headless=c["headless"], slow_mo=slow)
            if c["channel"] != "chromium":
                kwargs["channel"] = c["channel"]
            if not c["headless"]:
                kwargs["args"] = ["--start-maximized"]
            try:
                self.browser = p.chromium.launch(**kwargs)
            except Exception as e:
                msg = str(e).splitlines()[0]
                if "XServer" in str(e) or "Missing X server" in str(e):
                    raise RuntimeError("there's no screen to show the browser on. Run with --headless, "
                                       "or start it from a desktop session.")
                if "Executable doesn't exist" in str(e) or "is not found" in str(e) or "not found" in msg:
                    name = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}.get(c["channel"], "Chromium")
                    raise RuntimeError(
                        f"{name} isn't installed where Playwright looks for it. Install it, or set "
                        f"'channel: chromium' under browser: and run:  python -m playwright install chromium")
                raise
            if c["headless"]:
                context = self.browser.new_context(viewport={"width": 1440, "height": 900})
            else:
                context = self.browser.new_context(no_viewport=True)
        self.page = context.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.bring_to_front()

    def close(self):
        try:
            if self.cfg["attach"]:
                self.page.close()        # leave your own browser running
            else:
                self.browser.close()
        except Exception:
            pass

    # ---- helpers ------------------------------------------------------------

    def settle(self, timeout=15000):
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except PWTimeout:
            pass
        except Exception:
            pass
        self.page.wait_for_timeout(600)

    def window_spec(self):
        try:
            title = self.page.title()
        except Exception:
            title = ""
        mac_app = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "chromium": "Chromium"}[self.cfg["channel"]]
        return WindowSpec(contains=[title] if title else [], mac_app=mac_app)

    def focus(self):
        """Bring the browser window and this tab to the front."""
        if self.ctx.desktop_on and not self.cfg["headless"]:
            if not self.ctx.desktop.focus(self.window_spec()):
                self.ctx.desktop.focus(WindowSpec(contains=[], mac_app=self.window_spec().mac_app))
            self.ctx.human.script_acted()
        try:
            self.page.bring_to_front()
        except Exception:
            pass

    def glide_css(self, x, y, duration=None):
        if not self.ctx.cursor_on:
            return
        o = self.page.evaluate(ORIGIN_JS)
        s = self.ctx.desktop.css_scale(o["dpr"])
        self.ctx.human.glide((o["x"] + x) * s, (o["y"] + y) * s, duration or self.ctx.t["cursor_move"])

    def glide_to(self, locator):
        if not self.ctx.cursor_on:
            return
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
            box = locator.bounding_box()
        except Exception:
            return
        if box:
            self.glide_css(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    def click(self, locator):
        self.glide_to(locator)
        self.ctx.human.check()
        locator.click(timeout=10000)

    def resolve(self, target, kind="click", scope=None, timeout=10.0):
        """Find a visible element by its text, label, placeholder or a selector."""
        root = scope or self.page
        deadline = time.monotonic() + timeout
        while True:
            el = self._resolve_once(root, target, kind)
            if el is not None:
                return el
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.4)

    def _resolve_once(self, root, target, kind):
        q = target.replace('"', '\\"')
        if looks_like_selector(target):
            cands = [root.locator(target)]
        elif kind == "field":
            cands = [root.get_by_placeholder(target), root.get_by_label(target),
                     root.get_by_role("textbox", name=target), root.locator(f'[aria-label*="{q}" i]')]
        else:
            prefix = re.compile(r"^\s*" + re.escape(target), re.I)
            cands = [root.get_by_role("button", name=target, exact=True),
                     root.get_by_role("link", name=target, exact=True),
                     root.get_by_role("tab", name=target, exact=True),
                     root.get_by_role("menuitem", name=target, exact=True),
                     root.get_by_text(target, exact=True),
                     root.get_by_role("button", name=target),
                     root.get_by_role("link", name=target),
                     root.get_by_text(prefix),
                     root.get_by_text(target),
                     root.locator(f'[aria-label*="{q}" i], [title*="{q}" i]')]
        for c in cands:
            try:
                n = c.count()
                for i in range(min(n, 6)):
                    el = c.nth(i)
                    if el.is_visible():
                        return el
            except Exception:
                continue
        return None

    # ---- login ---------------------------------------------------------------

    def _first_visible(self, selector, timeout=0.0):
        deadline = time.monotonic() + timeout
        while True:
            loc = self.page.locator(selector)
            try:
                for i in range(min(loc.count(), 6)):
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.3)

    def _field(self, setting, auto_selector, timeout):
        if setting and setting != "auto":
            return self.resolve(setting, "field", timeout=timeout)
        return self._first_visible(auto_selector, timeout)

    def is_logged_in(self):
        lg = self.cfg["login"]
        if lg and lg.get("logged_in_when"):
            return self.resolve(str(lg["logged_in_when"]), "click", timeout=3) is not None
        return self._first_visible(PASSWORD_SELECTORS) is None

    def ensure_logged_in(self, creds):
        lg = self.cfg["login"]
        url = urljoin(self.cfg["site"] + "/", lg["url"]) if lg and lg.get("url") else self.cfg["site"]
        self.page.goto(url, wait_until="domcontentloaded")
        self.settle()
        if not lg:
            return "no login"
        if lg.get("logged_in_when") and self.is_logged_in():
            return "already signed in"

        email = self._field(lg["email_field"], EMAIL_SELECTORS, 10)
        pwd = self._field(lg["password_field"], PASSWORD_SELECTORS, 0 if email else 5)
        if not email and not pwd:
            if lg.get("logged_in_when"):
                raise RuntimeError(f"couldn't find a login form at {url}, and '{lg['logged_in_when']}' isn't "
                                   "on the page either. Set login.url to the sign-in page.")
            return "already signed in (no login form found)"

        user, password = creds.get()
        self.focus()
        if email:
            self.click(email)
            email.fill(user)
            if not pwd:
                # Two-step login: email first, then the password page.
                nxt = self._submit_button(lg)
                if nxt is not None:
                    self.click(nxt)
                else:
                    email.press("Enter")
                pwd = self._field(lg["password_field"], PASSWORD_SELECTORS, 15)
                if not pwd:
                    raise RuntimeError("entered the email, but no password box appeared.")
        self.click(pwd)
        pwd.fill(password)
        btn = self._submit_button(lg)
        if btn is not None:
            self.click(btn)
        else:
            pwd.press("Enter")

        if lg.get("logged_in_when"):
            if self.resolve(str(lg["logged_in_when"]), "click", timeout=30) is None:
                raise RuntimeError(f"logged in, but '{lg['logged_in_when']}' never appeared. "
                                   "Wrong email/password, or a captcha / 2-factor step?")
        else:
            try:
                self.page.locator(PASSWORD_SELECTORS).first.wait_for(state="hidden", timeout=30000)
            except Exception:
                raise RuntimeError("the password box is still showing after submitting. "
                                   "Wrong email/password, or a captcha / 2-factor step?")
        self.settle()
        return "signed in"

    def _submit_button(self, lg):
        if lg["submit_button"] != "auto":
            return self.resolve(lg["submit_button"], "click", timeout=5)
        for role in ("button", "link"):
            loc = self.page.get_by_role(role, name=SUBMIT_RE)
            try:
                for i in range(min(loc.count(), 6)):
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:
                pass
        return self._first_visible('button[type="submit"], input[type="submit"]')

    # ---- pages ---------------------------------------------------------------

    def discover_pages(self):
        c = self.cfg
        if c["pages"] != "auto":
            out = []
            for p in c["pages"]:
                if re.match(r"https?://", p) or p.startswith("/"):
                    out.append(PageRef(p, urljoin(c["site"] + "/", p), direct=True))
                else:
                    out.append(PageRef(p))
            if c["nav_area"] != "auto":
                self.nav_area = c["nav_area"]
            return out
        found = self.page.evaluate(DISCOVER_JS, {"areaSel": c["nav_area"], "skip": c["skip"]})
        if found.get("error"):
            raise RuntimeError(f"nav_area '{c['nav_area']}' isn't a valid CSS selector.")
        self.nav_area = found.get("area")
        return [PageRef(i["label"], i.get("href")) for i in found.get("items", [])]

    def _nav_scope(self):
        if self.nav_area:
            loc = self.page.locator(self.nav_area)
            try:
                for i in range(min(loc.count(), 8)):
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:
                pass
        return None

    def open_page(self, ref):
        """Navigate to a page: click its menu item like a person, or go to its URL."""
        if ref.direct:
            self.page.goto(ref.url, wait_until="domcontentloaded")
            return
        item = None
        scope = self._nav_scope()
        if scope is not None:
            item = self.resolve(ref.label, "click", scope=scope, timeout=4)
        if item is None:
            item = self.resolve(ref.label, "click", timeout=4)
        if item is not None:
            self.click(item)
        elif ref.url:
            self.page.goto(ref.url, wait_until="domcontentloaded")
        else:
            raise StepFailed(f"menu item '{ref.label}' not found")

    def actions_for(self, ref):
        out = []
        n = self.visit_count.get(ref.label, 0)
        for a in self.cfg["actions"]:
            name = a["page"].strip().lower()
            if name == "*" or ref.label.lower().startswith(name) or name in ref.label.lower():
                if n % a["every"] == 0:
                    out.append(a)
        return out

    # ---- steps -----------------------------------------------------------------

    def run_steps(self, steps, checks):
        page = self.page
        for s in steps:
            self.ctx.raise_if_out_of_time()
            act, val = s["action"], s["value"]
            if act == "click":
                el = self.resolve(val, "click", timeout=s.get("timeout") or 10)
                if el is None:
                    raise StepFailed(f"couldn't find '{val}' to click")
                self.click(el)
                self.settle(8000)
            elif act == "type":
                if s.get("into"):
                    el = self.resolve(s["into"], "field", timeout=s.get("timeout") or 10)
                    if el is None:
                        raise StepFailed(f"couldn't find the box '{s['into']}' to type into")
                else:
                    el = self._first_visible(TYPEABLE, 10)
                    if el is None:
                        raise StepFailed("couldn't find a text box to type into (add 'into:')")
                self.click(el)
                self.ctx.human.check()
                el.press_sequentially(val, delay=self.ctx.t["typing_delay"])
            elif act == "press":
                self.ctx.human.check()
                page.keyboard.press(browser_key(val))
                self.settle(5000)
            elif act == "wait":
                self.ctx.sleep(val)
            elif act == "scroll":
                to = val if val in ("top", "bottom") else None
                step = self.ctx.t["scroll_step"] * (-1 if val == "up" else 1)
                page.evaluate(SCROLL_JS, {"step": step, "to": to})
                self.ctx.sleep(0.8)
            elif act == "wander":
                self.browse(val, scroll=False)
            elif act == "goto":
                page.goto(urljoin(self.cfg["site"] + "/", val), wait_until="domcontentloaded")
                self.settle()
            elif act == "expect":
                found = self.resolve(val, "click", timeout=s.get("timeout") or 30) is not None
                checks.append((val, found))

    # ---- browsing ----------------------------------------------------------------

    def browse(self, seconds, scroll=True):
        """Stay on the page: wander the cursor and scroll slowly down and back up."""
        ctx = self.ctx
        page = self.page
        try:
            page.evaluate("() => { window.__apScroller = null; }")
            size = page.evaluate("() => [window.innerWidth, window.innerHeight]")
        except Exception:
            size = [1200, 800]
        end = ctx.active_deadline(seconds)
        direction = 1
        while not ctx.passed(end):
            ctx.human.check()
            if scroll:
                try:
                    r = page.evaluate(SCROLL_JS, {"step": ctx.t["scroll_step"] * direction, "to": None})
                    if r["scrolls"] and r["atEnd"]:
                        direction = -direction
                except Exception:
                    pass
            if ctx.cursor_on:
                x = random.uniform(0.15, 0.92) * size[0]
                y = random.uniform(0.18, 0.88) * size[1]
                self.glide_css(x, y, ctx.t["cursor_move"] * random.uniform(0.8, 1.5))
            ctx.sleep(random.uniform(ctx.t["gap_min"], ctx.t["gap_max"]))
        if scroll:
            try:
                page.evaluate(SCROLL_JS, {"step": 0, "to": "top"})
            except Exception:
                pass
