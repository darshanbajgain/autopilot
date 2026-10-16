"""Loading, defaults and validation of a settings (recipe) file."""
import copy
import re
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------
# Durations and speed
# --------------------------------------------------------------------------

def parse_duration(value, where, allow_forever=False):
    """'30s', '5m', '1h30m', '90', 'forever' -> seconds (float, or None for forever)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if allow_forever and text in ("forever", "always", "0", "never stop"):
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)", text)
    if not parts or re.sub(r"[\d.\shrminsecoudt]", "", text):
        raise ConfigError(f"{where}: '{value}' isn't a duration. Use something like 30s, 5m, 1h or 1h30m"
                          + (" (or 'forever')." if allow_forever else "."))
    total = 0.0
    for num, unit in parts:
        mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        total += float(num) * mult
    return total


def fmt_duration(seconds):
    if seconds is None:
        return "forever"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    out = (f"{h}h" if h else "") + (f"{m}m" if m else "") + (f"{s}s" if s and not h else "")
    return out or "0s"


SPEEDS = {
    #          cursor glide s, scroll px, gap between moves (min, max) s, typing delay ms
    "slow":   {"cursor_move": 1.8, "scroll_step": 150, "gap_min": 1.2, "gap_max": 2.5, "typing_delay": 140},
    "normal": {"cursor_move": 1.2, "scroll_step": 250, "gap_min": 0.6, "gap_max": 1.5, "typing_delay": 80},
    "fast":   {"cursor_move": 0.6, "scroll_step": 450, "gap_min": 0.3, "gap_max": 0.8, "typing_delay": 35},
}

STEP_ACTIONS = ("click", "type", "press", "wait", "scroll", "wander", "goto", "expect")
STEP_MODIFIERS = ("into", "timeout")
BROWSER_ONLY = ("click", "goto", "expect")

DEFAULT_SKIP = ["log out", "logout", "sign out", "signout", "delete", "remove account"]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"Settings file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise ConfigError(f"{path.name}{where}: this isn't valid YAML. Check indentation (spaces, not tabs) "
                          f"and that text with ':' or '#' is in quotes.\n  {getattr(e, 'problem', e)}")
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: expected settings like 'run_for: 1h' at the top level.")
    cfg = normalize(raw)
    cfg["_path"] = str(path.resolve())
    cfg["_dir"] = str(path.resolve().parent)
    return cfg


def _check_keys(d, allowed, where):
    unknown = [k for k in d if k not in allowed]
    if unknown:
        raise ConfigError(f"{where}: unknown setting(s) {', '.join(map(repr, unknown))}. "
                          f"Allowed here: {', '.join(allowed)}.")


def _bool(v, where):
    if isinstance(v, bool):
        return v
    if str(v).lower() in ("yes", "true", "on", "1"):
        return True
    if str(v).lower() in ("no", "false", "off", "0"):
        return False
    raise ConfigError(f"{where}: expected yes or no, got '{v}'.")


def _list_of_str(v, where):
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    if isinstance(v, list) and all(isinstance(x, (str, int, float)) for x in v):
        return [str(x) for x in v]
    raise ConfigError(f"{where}: expected a list of names.")


def normalize_steps(steps, where, in_browser):
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise ConfigError(f"{where}: 'steps' must be a list, each line starting with '- '.")
    out = []
    for i, step in enumerate(steps, 1):
        w = f"{where}, step {i}"
        if not isinstance(step, dict):
            raise ConfigError(f"{w}: each step looks like '- click: \"Save\"' or '- wait: 5s'.")
        actions = [k for k in step if k in STEP_ACTIONS]
        _check_keys(step, STEP_ACTIONS + STEP_MODIFIERS, w)
        if len(actions) != 1:
            raise ConfigError(f"{w}: put exactly one action in each step "
                              f"(one of: {', '.join(STEP_ACTIONS)}).")
        action = actions[0]
        if action in BROWSER_ONLY and not in_browser:
            raise ConfigError(f"{w}: '{action}' only works on websites, not in desktop apps.")
        if "into" in step and action != "type":
            raise ConfigError(f"{w}: 'into' only goes with 'type'.")
        s = {"action": action, "value": step[action]}
        if action in ("wait", "wander"):
            s["value"] = parse_duration(step[action], w)
        elif action == "scroll":
            val = str(step[action]).lower()
            if val not in ("down", "up", "top", "bottom"):
                raise ConfigError(f"{w}: scroll can be down, up, top or bottom.")
            s["value"] = val
        else:
            if step[action] is None or str(step[action]) == "":
                raise ConfigError(f"{w}: '{action}' needs a value.")
            s["value"] = str(step[action])
        if "into" in step:
            s["into"] = str(step["into"])
        if "timeout" in step:
            s["timeout"] = parse_duration(step["timeout"], w)
        out.append(s)
    return out


def normalize(raw):
    raw = copy.deepcopy(raw)
    top = ("run_for", "speed", "tuning", "real_cursor", "pause_when_touched", "resume_after",
           "browser", "apps")
    _check_keys(raw, top, "Settings file")

    cfg = {
        "run_for": parse_duration(raw.get("run_for", "forever"), "run_for", allow_forever=True),
        "real_cursor": _bool(raw.get("real_cursor", True), "real_cursor"),
        "pause_when_touched": _bool(raw.get("pause_when_touched", True), "pause_when_touched"),
        "resume_after": parse_duration(raw.get("resume_after", "15s"), "resume_after"),
    }

    speed = str(raw.get("speed", "normal")).lower()
    if speed not in SPEEDS:
        raise ConfigError(f"speed: use slow, normal or fast (got '{speed}').")
    cfg["speed"] = speed
    tuning = dict(SPEEDS[speed])
    t = raw.get("tuning") or {}
    if not isinstance(t, dict):
        raise ConfigError("tuning: expected settings like 'cursor_move: 1.5'.")
    _check_keys(t, tuple(tuning), "tuning")
    for k, v in t.items():
        try:
            tuning[k] = float(v)
        except (TypeError, ValueError):
            raise ConfigError(f"tuning.{k}: expected a number, got '{v}'.")
    if tuning["gap_max"] < tuning["gap_min"]:
        tuning["gap_max"] = tuning["gap_min"]
    cfg["tuning"] = tuning

    # ---- browser -----------------------------------------------------------
    b = raw.get("browser")
    if b in (None, False):
        cfg["browser"] = None
    else:
        if not isinstance(b, dict):
            raise ConfigError("browser: expected settings like 'site: https://example.com' under it.")
        allowed = ("site", "attach", "channel", "headless", "login", "pages", "nav_area", "skip",
                   "stay_on_page", "order", "actions")
        _check_keys(b, allowed, "browser")
        site = b.get("site")
        if not site or not re.match(r"https?://", str(site)):
            raise ConfigError("browser.site: give the full address, starting with https:// "
                              "(for example https://example.com).")
        channel = str(b.get("channel", "chrome")).lower()
        if channel not in ("chrome", "msedge", "chromium"):
            raise ConfigError("browser.channel: use chrome, msedge or chromium.")
        order = str(b.get("order", "in_order")).lower().replace(" ", "_")
        if order not in ("in_order", "random"):
            raise ConfigError("browser.order: use in_order or random.")

        pages = b.get("pages", "auto")
        if isinstance(pages, str) and pages.strip().lower() == "auto":
            pages = "auto"
        else:
            pages = _list_of_str(pages, "browser.pages")
            if not pages:
                raise ConfigError("browser.pages: list at least one page, or write 'auto'.")

        login = b.get("login", None)
        if login in (None, False):
            login = None
        else:
            if login is True:
                login = {}
            if not isinstance(login, dict):
                raise ConfigError("browser.login: expected 'yes', 'no', or settings under it.")
            lallowed = ("url", "credentials", "email_field", "password_field", "submit_button",
                        "logged_in_when", "email_env", "password_env")
            _check_keys(login, lallowed, "browser.login")
            mode = str(login.get("credentials", "ask")).lower()
            if mode not in ("ask", "saved", "env"):
                raise ConfigError("browser.login.credentials: use ask, saved or env.")
            login = {
                "url": login.get("url"),
                "credentials": mode,
                "email_field": str(login.get("email_field", "auto")),
                "password_field": str(login.get("password_field", "auto")),
                "submit_button": str(login.get("submit_button", "auto")),
                "logged_in_when": login.get("logged_in_when"),
                "email_env": str(login.get("email_env", "AUTOPILOT_EMAIL")),
                "password_env": str(login.get("password_env", "AUTOPILOT_PASSWORD")),
            }

        actions = []
        for i, a in enumerate(b.get("actions") or [], 1):
            w = f"browser.actions #{i}"
            if not isinstance(a, dict) or "page" not in a:
                raise ConfigError(f"{w}: each action needs 'page:' (a page name, or '*' for every page) "
                                  "and 'steps:'.")
            _check_keys(a, ("page", "steps", "every"), w)
            actions.append({
                "page": str(a["page"]),
                "every": int(a.get("every", 1)),
                "steps": normalize_steps(a.get("steps"), f"{w} (page '{a['page']}')", True),
            })

        cfg["browser"] = {
            "site": str(site).rstrip("/"),
            "attach": _bool(b.get("attach", False), "browser.attach"),
            "channel": channel,
            "headless": _bool(b.get("headless", False), "browser.headless"),
            "login": login,
            "pages": pages,
            "nav_area": str(b.get("nav_area", "auto")),
            "skip": [s.lower() for s in _list_of_str(b.get("skip", DEFAULT_SKIP), "browser.skip")],
            "stay_on_page": parse_duration(b.get("stay_on_page", "30s"), "browser.stay_on_page"),
            "order": order,
            "actions": actions,
        }

    # ---- apps --------------------------------------------------------------
    a = raw.get("apps")
    if a in (None, False, []):
        cfg["apps"] = None
    else:
        if isinstance(a, list):
            a = {"list": a}
        if not isinstance(a, dict):
            raise ConfigError("apps: expected 'every:', 'stay:' and 'list:' under it.")
        _check_keys(a, ("every", "stay", "list"), "apps")
        items = []
        for i, app in enumerate(a.get("list") or [], 1):
            w = f"apps.list #{i}"
            if isinstance(app, str):
                app = {"app": app}
            if not isinstance(app, dict):
                raise ConfigError(f"{w}: expected 'app: vscode' (or cursor, or a 'command:').")
            _check_keys(app, ("name", "app", "folder", "command", "window_title", "mac_app",
                              "steps", "typing_target", "stay"), w)
            kind = str(app.get("app", "custom")).lower().replace(" ", "")
            kind = {"code": "vscode", "visualstudiocode": "vscode"}.get(kind, kind)
            if kind not in ("vscode", "cursor", "custom"):
                raise ConfigError(f"{w}: app can be vscode, cursor, or custom (with command: and "
                                  "window_title:).")
            if kind == "custom" and not (app.get("command") or app.get("mac_app")):
                raise ConfigError(f"{w}: a custom app needs 'command:' (how to start it) and "
                                  "'window_title:' (text in its window title).")
            target = str(app.get("typing_target", "scratch" if kind != "custom" else "focused")).lower()
            if target not in ("scratch", "focused"):
                raise ConfigError(f"{w}: typing_target can be scratch or focused.")
            if target == "scratch" and kind == "custom":
                raise ConfigError(f"{w}: typing_target: scratch only works with vscode or cursor.")
            folder = app.get("folder")
            items.append({
                "name": str(app.get("name") or {"vscode": "VS Code", "cursor": "Cursor"}.get(kind)
                            or app.get("window_title") or app.get("command")),
                "app": kind,
                "folder": str(Path(str(folder)).expanduser()) if folder else None,
                "command": app.get("command"),
                "window_title": app.get("window_title"),
                "mac_app": app.get("mac_app"),
                "typing_target": target,
                "stay": parse_duration(app["stay"], f"{w}.stay") if "stay" in app else None,
                "steps": normalize_steps(app.get("steps"), w, False),
            })
        if not items:
            raise ConfigError("apps: 'list:' is empty. Add e.g. '- app: vscode'.")
        cfg["apps"] = {
            "every": max(1, int(a.get("every", 3))),
            "stay": parse_duration(a.get("stay", "40s"), "apps.stay"),
            "list": items,
        }

    if not cfg["browser"] and not cfg["apps"]:
        raise ConfigError("Nothing to do: add a 'browser:' section, an 'apps:' section, or both.")
    return cfg
