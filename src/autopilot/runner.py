"""The run loop: website pages in rounds, with desktop app visits mixed in,
until the time is up or you press Ctrl+C."""
import os
import random
import time
from pathlib import Path

from .apps import AppVisitor
from .config import fmt_duration
from .creds import Credentials
from .desktop import Desktop, LINUX, MAC, WINDOWS, os_name
from .human import Human
from .report import Report


class OutOfTime(Exception):
    pass


def log(msg=""):
    print(msg, flush=True)


def find_running_browser(channel):
    """Debugging endpoint of an already-open Chrome/Edge (remote debugging enabled
    at chrome://inspect/#remote-debugging), or the classic port 9222."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    dirs = {
        "chrome": [local / "Google/Chrome/User Data", home / "Library/Application Support/Google/Chrome",
                   home / ".config/google-chrome"],
        "msedge": [local / "Microsoft/Edge/User Data", home / "Library/Application Support/Microsoft Edge",
                   home / ".config/microsoft-edge"],
        "chromium": [local / "Chromium/User Data", home / "Library/Application Support/Chromium",
                     home / ".config/chromium"],
    }[channel]
    for d in dirs:
        f = d / "DevToolsActivePort"
        if f.is_file():
            lines = f.read_text().split()
            if len(lines) >= 2:
                return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
    return "http://127.0.0.1:9222"


class Context:
    """Shared state for one run."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.t = cfg["tuning"]
        self.log = log
        self.run_end = None if cfg["run_for"] is None else time.monotonic() + cfg["run_for"]
        b = cfg["browser"]
        headless_only = bool(b and b["headless"]) and not cfg["apps"]
        wants_desktop = (cfg["real_cursor"] or cfg["pause_when_touched"] or cfg["apps"]) and not headless_only
        self.desktop = Desktop() if wants_desktop else None
        self.desktop_on = bool(self.desktop and self.desktop.ok)
        self.cursor_on = self.desktop_on and cfg["real_cursor"]
        self.human = Human(self.desktop or _NoDesktop(), self.desktop_on and cfg["pause_when_touched"],
                           cfg["resume_after"], log)

    def time_left(self):
        return None if self.run_end is None else self.run_end - time.monotonic()

    def raise_if_out_of_time(self):
        if self.run_end is not None and time.monotonic() >= self.run_end:
            raise OutOfTime()

    def sleep(self, seconds):
        left = self.time_left()
        if left is not None:
            seconds = min(seconds, max(0.0, left))
        self.human.sleep(seconds)
        self.raise_if_out_of_time()

    def active_deadline(self, seconds):
        """A timer that doesn't count time spent paused for you."""
        return (time.monotonic(), self.human.paused_total, seconds)

    def passed(self, deadline):
        start, paused0, seconds = deadline
        self.raise_if_out_of_time()
        return time.monotonic() - start - (self.human.paused_total - paused0) >= seconds


class _NoDesktop:
    ok = False

    def position(self):
        return (0, 0)


def describe(cfg, ctx):
    """Print what the run is going to do."""
    b, a = cfg["browser"], cfg["apps"]
    log(f"Autopilot on {os_name()} - run for {fmt_duration(cfg['run_for'])}, speed {cfg['speed']}.")
    if b:
        pages = "found automatically" if b["pages"] == "auto" else ", ".join(b["pages"])
        log(f"  Website: {b['site']}  ({'your open browser' if b['attach'] else b['channel']}"
            f"{', no window' if b['headless'] else ''})")
        log(f"  Pages: {pages}; {fmt_duration(b['stay_on_page'])} on each, {b['order'].replace('_', ' ')}.")
        if b["actions"]:
            log(f"  Actions on: {', '.join(x['page'] for x in b['actions'])}")
    if a:
        log(f"  Apps: {', '.join(x['name'] for x in a['list'])} - one after every {a['every']} page(s)"
            if b else f"  Apps: {', '.join(x['name'] for x in a['list'])}")
    if ctx.desktop and not ctx.desktop.ok:
        log(f"  Note: real cursor, app switching and pause-on-touch are off: {ctx.desktop.reason}")
    elif ctx.human.enabled:
        how = "mouse or keyboard" if ctx.human.keyboard_aware else "mouse"
        log(f"  Touch the {how} to pause; it resumes after {fmt_duration(cfg['resume_after'])} idle.")
    log("  Stop: press Ctrl+C in this terminal.\n")


def run(cfg, countdown=0):
    from playwright.sync_api import sync_playwright

    ctx = Context(cfg)
    report = Report(log)
    describe(cfg, ctx)
    b, a = cfg["browser"], cfg["apps"]
    if a and not ctx.desktop_on:
        log("Desktop apps need the desktop features above, so they'll be skipped.\n")
        a = None
        if not b:
            return False

    creds = Credentials(b["login"], b["site"], cfg["_path"], log) if b and b["login"] else None
    if creds and creds.mode == "ask" and not b["attach"]:
        creds.get()          # ask now, before windows start opening

    if countdown and ctx.desktop_on:
        try:
            for i in range(int(countdown), 0, -1):
                print(f"\rStarting in {i}s - hands off the mouse (Ctrl+C to cancel) ", end="", flush=True)
                time.sleep(1)
            print("\r" + " " * 64 + "\r", end="")
        except KeyboardInterrupt:
            log("\nCancelled.")
            return True

    apps = AppVisitor(ctx) if a else None
    app_turn = 0
    from . import store
    base = store.home() if Path(cfg["_dir"]) == store.setups_dir() else Path(cfg["_dir"])
    reports_dir = base / "reports"
    shots_dir = base / "screenshots"

    def visit_app():
        nonlocal app_turn
        app = a["list"][app_turn % len(a["list"])]
        app_turn += 1
        stay = app["stay"] or a["stay"]
        start = time.monotonic()
        try:
            apps.visit(app, stay)
            report.add("app", app["name"], True, time.monotonic() - start)
        except (OutOfTime, KeyboardInterrupt):
            report.add("app", app["name"], True, time.monotonic() - start)
            raise
        except Exception as e:
            report.add("app", app["name"], False, time.monotonic() - start, [str(e).splitlines()[0][:120]])

    with sync_playwright() as p:
        web = None
        try:
            if b:
                from .browser import Browser, StepFailed
                web = Browser(b, ctx)
                web.start(p, lambda: find_running_browser(b["channel"]))
                ctx.human.script_acted()
                log("Opening the site...")
                try:
                    state = web.ensure_logged_in(creds)
                except (KeyboardInterrupt, OutOfTime):
                    raise
                except Exception as e:
                    shots_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        web.page.screenshot(path=str(shots_dir / "login_failed.png"), full_page=True)
                    except Exception:
                        pass
                    log(f"LOGIN FAILED: {e}")
                    log(f"(Screenshot saved to {shots_dir / 'login_failed.png'})")
                    report.stop_reason = "login failed"
                    return False
                log(f"  {state} -> {web.page.url}")
                pages = web.discover_pages()
                if not pages:
                    log("No pages found to visit. List them under browser: pages:, or set nav_area: "
                        "to the menu's CSS selector. Run 'autopilot check' to see what's found.")
                    report.stop_reason = "no pages"
                    return False
                log(f"  Pages: {', '.join(p_.label for p_ in pages)}\n")

            round_no = 0
            pages_seen = 0
            while True:
                round_no += 1
                if b:
                    log(f"--- Round {round_no} ---")
                    order = list(pages)
                    if b["order"] == "random":
                        random.shuffle(order)
                    for ref in order:
                        ctx.raise_if_out_of_time()
                        web.focus()
                        ctx.human.on_resume = web.focus
                        web.errors.clear()
                        checks, notes, ok = [], [], True
                        start = time.monotonic()
                        try:
                            ctx.human.check()
                            try:
                                web.open_page(ref)
                            except StepFailed:
                                # Menu missing: maybe the session expired.
                                if not (web.cfg["login"] and not web.is_logged_in()):
                                    raise
                                log("   (signed out - logging in again)")
                                web.ensure_logged_in(creds)
                                web.open_page(ref)
                            web.settle()
                            for action in web.actions_for(ref):
                                web.run_steps(action["steps"], checks)
                            web.browse(b["stay_on_page"])
                        except (KeyboardInterrupt, OutOfTime):
                            report.add("page", ref.label, ok, time.monotonic() - start, notes,
                                       len(web.errors), checks)
                            raise
                        except Exception as e:
                            ok = False
                            notes.append(str(e).splitlines()[0][:120])
                            shots_dir.mkdir(parents=True, exist_ok=True)
                            safe = "".join(ch if ch.isalnum() else "_" for ch in ref.label)[:30]
                            try:
                                web.page.screenshot(path=str(shots_dir / f"r{round_no}_{safe}_failed.png"))
                            except Exception:
                                pass
                        web.visit_count[ref.label] = web.visit_count.get(ref.label, 0) + 1
                        report.add("page", ref.label, ok, time.monotonic() - start, notes,
                                   len(web.errors), checks)
                        pages_seen += 1
                        if a and pages_seen % a["every"] == 0:
                            visit_app()
                else:
                    for _ in a["list"]:
                        visit_app()
        except OutOfTime:
            report.stop_reason = f"time's up ({fmt_duration(cfg['run_for'])})"
        except KeyboardInterrupt:
            report.stop_reason = "stopped with Ctrl+C"
        finally:
            if web:
                web.close()
    return report.summary(reports_dir)
