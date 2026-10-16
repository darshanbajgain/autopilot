"""'autopilot setup' / 'autopilot edit': asks for everything once (site,
login, pages, actions and keystrokes, code editors, timing) and saves it as a
setup that every later run uses."""
import getpass
import re
import sys

from . import store
from .config import ConfigError, parse_duration
from .creds import host_of, save_login, saved_login, store_available


# --------------------------------------------------------------------------
# Small question helpers
# --------------------------------------------------------------------------

def ask(prompt, default=None, allow_empty=False):
    hint = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            ans = input(f"{prompt}{hint}: ").strip()
        except EOFError:
            raise KeyboardInterrupt
        if not ans and default not in (None, ""):
            return str(default)
        if ans or allow_empty:
            return ans
        print("  (please type an answer)")


def yes(prompt, default=True):
    while True:
        ans = ask(prompt + (" (Y/n)" if default else " (y/N)"), "", allow_empty=True).lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  (y or n)")


def choose(prompt, options, default=1):
    """options: list of labels. Returns the 1-based number chosen."""
    for i, label in enumerate(options, 1):
        print(f"    {i}) {label}")
    while True:
        ans = ask(f"  {prompt}", str(default))
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return int(ans)
        print(f"  (a number from 1 to {len(options)})")


def choose_many(prompt, options, default="1"):
    """Returns a sorted list of 1-based numbers, e.g. from '1,3'."""
    for i, label in enumerate(options, 1):
        print(f"    {i}) {label}")
    while True:
        ans = ask(f"  {prompt}", default)
        nums = [int(x) for x in re.findall(r"\d+", ans)]
        if nums and all(1 <= n <= len(options) for n in nums):
            return sorted(set(nums))
        print(f"  (numbers from 1 to {len(options)}, like 1 or 1,3)")


def duration(prompt, default, allow_forever=False):
    while True:
        ans = ask(prompt, default)
        try:
            parse_duration(ans, prompt, allow_forever)
            return ans
        except ConfigError:
            print("  (like 30s, 5m, 2h, 1h30m" + (", or forever)" if allow_forever else ")"))


def number(prompt, default):
    while True:
        ans = ask(prompt, str(default))
        if ans.isdigit() and int(ans) >= 1:
            return int(ans)
        print("  (a whole number, 1 or more)")


def section(n, total, title):
    print(f"\n=== {n}/{total}  {title} " + "=" * max(3, 50 - len(title)))


KNOWN_KEYS = {
    "enter", "return", "esc", "escape", "tab", "space", "backspace", "delete", "del", "up", "down",
    "left", "right", "home", "end", "pageup", "pagedown", "pgup", "pgdn", "insert", "ctrl", "control",
    "shift", "alt", "option", "cmd", "command", "meta", "win", "super", "mod",
}


def valid_key(combo):
    parts = [p.strip().lower() for p in re.split(r"\+(?!$)", combo) if p.strip()]
    return bool(parts) and all(p in KNOWN_KEYS or len(p) == 1 or re.fullmatch(r"f\d{1,2}", p)
                               or p.startswith("arrow") for p in parts)


KEYS_HELP = """    One per line, then an empty line to finish:
      mod+p            press a shortcut (mod = Ctrl on Windows/Linux, Cmd on Mac)
      Enter            press a key (Enter, Escape, Tab, Up, Down, F5, ...)
      type README      type some text
      wait 2s          wait
      scroll down      scroll (down, up, top, bottom)"""


def keystrokes():
    print(KEYS_HELP)
    steps = []
    while True:
        try:
            line = input("      > ").strip()
        except EOFError:
            raise KeyboardInterrupt
        if not line:
            return steps
        low = line.lower()
        if low.startswith("type "):
            steps.append({"type": line[5:].replace("\\n", "\n")})
        elif low.startswith("wait "):
            try:
                parse_duration(line[5:], "wait")
                steps.append({"wait": line[5:].strip()})
            except ConfigError:
                print("      (wait needs a time like 2s)")
        elif low.startswith("scroll"):
            where = (low.split() + ["down"])[1]
            if where in ("down", "up", "top", "bottom"):
                steps.append({"scroll": where})
            else:
                print("      (scroll down, up, top or bottom)")
        elif valid_key(line):
            steps.append({"press": line})
        else:
            print("      (not a key I know - for text use: type your text)")


# --------------------------------------------------------------------------
# Looking at the site to list its pages
# --------------------------------------------------------------------------

class _FixedCreds:
    mode = "fixed"

    def __init__(self, email, pwd, raw_login, site, setup_path):
        self.email, self.pwd = email, pwd
        self.raw_login, self.site, self.setup_path = raw_login, site, setup_path

    def get(self):
        if self.email and self.pwd:
            return self.email, self.pwd
        from .creds import Credentials
        from .config import normalize
        cfg = normalize({"browser": {"site": self.site, "login": self.raw_login}})
        return Credentials(cfg["browser"]["login"], self.site, self.setup_path, print).get()


def discover_pages(raw_browser, creds):
    from playwright.sync_api import sync_playwright
    from .browser import Browser
    from .config import normalize
    from .runner import Context, find_running_browser

    braw = {k: v for k, v in raw_browser.items() if k not in ("actions", "pages")}
    braw["pages"] = "auto"
    cfg = normalize({"real_cursor": False, "pause_when_touched": False, "browser": braw})
    b = cfg["browser"]
    if not b["attach"]:
        b["headless"] = True
    ctx = Context(cfg)
    with sync_playwright() as p:
        web = Browser(b, ctx)
        try:
            web.start(p, lambda: find_running_browser(b["channel"]))
            web.ensure_logged_in(creds)
            return [r.label for r in web.discover_pages()]
        finally:
            web.close()


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def ask_general(old):
    raw = {}
    raw["run_for"] = duration("How long should each run last? (30m, 2h, forever)",
                              old.get("run_for", "2h"), allow_forever=True)
    speeds = ["slow", "normal", "fast"]
    cur = str(old.get("speed", "normal"))
    print("  Speed of the cursor, scrolling and typing:")
    raw["speed"] = speeds[choose("Speed", ["slow", "normal", "fast"],
                                 speeds.index(cur) + 1 if cur in speeds else 2) - 1]
    raw["real_cursor"] = yes("Move the real mouse cursor so you can watch it?", old.get("real_cursor", True))
    raw["pause_when_touched"] = yes("When you use the mouse/keyboard, pause and let you take over?",
                                    old.get("pause_when_touched", True))
    if raw["pause_when_touched"]:
        raw["resume_after"] = duration("  Continue after how long without mouse/keyboard use?",
                                       old.get("resume_after", "15s"))
    else:
        raw["resume_after"] = old.get("resume_after", "15s")
    return raw


def ask_login(name, site, old_login):
    had_login = old_login is None or isinstance(old_login, dict)   # new setups default to yes
    old_login = old_login if isinstance(old_login, dict) else {}
    if not yes("Does the site need a login?", had_login):
        return None, (None, None)
    login = {}
    email = pwd = None
    print("  Your email and password are kept in this computer's password store")
    print("  (never in the setup file), so runs don't ask for them.")
    if store_available():
        existing = saved_login(site)
        if existing and yes(f"  Saved login for {host_of(site)}: {existing}. Keep it?", True):
            email = existing
        else:
            email = ask("  Email / username")
            while True:
                pwd = getpass.getpass("  Password (hidden): ")
                if pwd:
                    break
            save_login(site, email, pwd)
            print("  Saved.")
        login["credentials"] = "saved"
    else:
        print("  This computer has no password store.")
        env = store.path_for(name).with_suffix(".env")
        old_mode = old_login.get("credentials")
        if old_mode == "env" and env.exists() and yes(f"  Keep the login saved in {env.name}?", True):
            login["credentials"] = "env"
            how = None
        elif old_mode == "ask" and yes("  Keep asking for it at the start of each run?", True):
            login["credentials"] = "ask"
            how = None
        else:
            how = 0
    if not store_available() and how == 0:
        how = choose("How should the login be given?", [
            "Ask me in the terminal at the start of each run",
            f"Save it in a file next to the setup ({store.slug(name)}.env, plain text, this computer only)"])
        if how == 1:
            login["credentials"] = "ask"
        else:
            email = ask("  Email / username")
            pwd = getpass.getpass("  Password (hidden): ")
            env = store.path_for(name).with_suffix(".env")
            env.write_text(f"AUTOPILOT_EMAIL={email}\nAUTOPILOT_PASSWORD={pwd}\n", encoding="utf-8")
            login["credentials"] = "env"
            print(f"  Saved to {env}")
    marker = ask("  Text that only shows once you're logged in, e.g. a menu item like 'Dashboard'\n"
                 "  (makes login detection reliable; Enter to skip)", old_login.get("logged_in_when", ""),
                 allow_empty=True)
    if marker:
        login["logged_in_when"] = marker
    url = ask("  Login page address, if it's not the site address (Enter to skip)", old_login.get("url", ""),
              allow_empty=True)
    if url:
        login["url"] = url
    for k in ("email_field", "password_field", "submit_button"):
        if old_login.get(k):
            login[k] = old_login[k]
    return login, (email, pwd)


def ask_web_steps(page):
    steps = []
    kinds = ["click a button, link or tab", "type text (into a chat box, search, ...)",
             "press a key or shortcut", "wait", "scroll", "check that some text appears", "done"]
    print(f"  Steps to do on '{page}', in order:")
    while True:
        k = choose("Add step", kinds, len(kinds))
        if k == 7:
            return steps
        if k == 1:
            steps.append({"click": ask("    Text on the button/link (or a CSS selector)")})
        elif k == 2:
            text = ask("    Text to type").replace("\\n", "\n")
            into = ask("    Which box? Its placeholder or label, e.g. 'Ask anything' (Enter = first text box)",
                       "", allow_empty=True)
            steps.append({"type": text, **({"into": into} if into else {})})
        elif k == 3:
            while True:
                key = ask("    Key or shortcut (Enter, Escape, mod+k, ctrl+shift+p ...)", "Enter")
                if valid_key(key):
                    break
                print("    (not a key I know)")
            steps.append({"press": key})
        elif k == 4:
            steps.append({"wait": duration("    How long?", "5s")})
        elif k == 5:
            where = ["down", "up", "top", "bottom"][choose("Scroll", ["down", "up", "to the top", "to the bottom"]) - 1]
            steps.append({"scroll": where})
        elif k == 6:
            steps.append({"expect": ask("    Text that should appear")})
            t = duration("    Wait up to", "30s")
            if t != "30s":
                steps[-1]["timeout"] = t
        print(f"    added: {list(steps[-1].items())[0][0]}")


def ask_website(name, old):
    oldb = old.get("browser") if isinstance(old.get("browser"), dict) else {}
    if not yes("Automate a website?", bool(oldb) or not old):
        return None
    b = {}
    while True:
        site = ask("Site address", oldb.get("site", "https://"))
        if re.match(r"https?://\S+\.\S+|https?://localhost", site):
            break
        print("  (the full address, like https://app.example.com)")
    b["site"] = site.rstrip("/")
    print("  Which browser window should it use?")
    w = choose("Browser", ["A separate Chrome window just for Autopilot (simplest)",
                           "The Chrome you already have open, as a new tab "
                           "(turn on chrome://inspect/#remote-debugging once)"],
               2 if oldb.get("attach") else 1)
    b["attach"] = w == 2
    if oldb.get("channel") and oldb.get("channel") != "chrome":
        b["channel"] = oldb["channel"]

    login, (email, pwd) = ask_login(name, b["site"], oldb.get("login"))
    b["login"] = login if login else False

    # Pages
    print()
    pages = None
    old_pages = oldb.get("pages")
    if isinstance(old_pages, list) and old_pages and yes(f"Keep the current pages ({', '.join(map(str, old_pages))})?", True):
        pages = list(old_pages)
    elif yes("Open the site now to list its menu pages so you can pick them?"
             + (" (Chrome asks you to Allow)" if b["attach"] else ""), True):
        print("  Opening the site ...")
        try:
            found = discover_pages(b, _FixedCreds(email, pwd, login, b["site"], store.path_for(name)))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            found = []
            print(f"  Couldn't list the pages: {str(e).splitlines()[0]}")
        if found:
            print(f"  Found {len(found)} pages:")
            nums = choose_many("Which to visit? (Enter = all, or numbers like 1,2,5)",
                               found, ",".join(str(i) for i in range(1, len(found) + 1)))
            pages = [found[i - 1] for i in nums]
        else:
            print("  No menu found automatically.")
    if pages is None:
        typed = ask("Page names to visit, as written in the menu, separated by commas\n"
                    "  (Enter = find them automatically each run)", "", allow_empty=True)
        pages = [p.strip() for p in typed.split(",") if p.strip()] or "auto"
    b["pages"] = pages
    b["stay_on_page"] = duration("How long to stay on each page (scrolling and moving around)?",
                                 oldb.get("stay_on_page", "30s"))
    o = choose("Visit order", ["In order", "Random"], 2 if oldb.get("order") == "random" else 1)
    b["order"] = "random" if o == 2 else "in_order"
    if oldb.get("skip"):
        b["skip"] = oldb["skip"]

    # Actions
    actions = []
    old_actions = oldb.get("actions") or []
    if old_actions and yes(f"Keep the current page actions ({', '.join(str(a.get('page')) for a in old_actions)})?", True):
        actions = list(old_actions)
    print("\nActions: things to do on a page, like typing into a chat or pressing keys.")
    while yes("Add an action on a page?" if not actions else "Add another page action?", False):
        if isinstance(pages, list):
            print("  On which page?")
            n = choose("Page", pages + ["every page", "another page (type its name)"])
            page = pages[n - 1] if n <= len(pages) else "*" if n == len(pages) + 1 else ask("    Page name")
        else:
            page = ask("  On which page? (menu text, or * for every page)")
        steps = ask_web_steps(page)
        if not steps:
            continue
        a = {"page": page}
        every = number("  Do this on every visit (1), or every how many visits?", 1)
        if every > 1:
            a["every"] = every
        a["steps"] = steps
        actions.append(a)
    if actions:
        b["actions"] = actions
    return b


EDITORS = {"vscode": "VS Code", "cursor": "Cursor"}


def ask_editor(kind, old_entries):
    label = EDITORS[kind]
    old_folder = next((e.get("folder") for e in old_entries if e.get("app") == kind and e.get("folder")), "")
    folder = ask(f"  {label}: project folder to open (Enter = don't open a folder)", old_folder, allow_empty=True)
    folder = folder.strip().strip('"')
    print(f"  What should it do in {label}? (it always looks around and scrolls too)")
    picks = choose_many("Pick one or more (like 2,5)", [
        "Just look around and scroll (safe)",
        "Open files with Quick Open (Ctrl/Cmd+P)",
        "Type text into a scratch tab (never into your files)",
        "Run a command from the Command Palette",
        "My own keystrokes",
    ], "1")
    focused, scratch = [], []
    if 2 in picks:
        files = ask("    File names to open, separated by commas", "README")
        for f in [x.strip() for x in files.split(",") if x.strip()]:
            focused += [{"press": "mod+p"}, {"wait": "1s"}, {"type": f}, {"wait": "1s"},
                        {"press": "Enter"}, {"wait": "3s"}, {"scroll": "down"}]
    if 4 in picks:
        cmd = ask("    Command Palette command", "View: Toggle Terminal")
        focused += [{"press": "mod+shift+p"}, {"wait": "1s"}, {"type": cmd}, {"wait": "1s"},
                    {"press": "Enter"}, {"wait": "3s"}]
    if 5 in picks:
        print(f"    Keystrokes to send to {label}. Note: 'type' text goes wherever {label}'s cursor is,")
        print("    which can be an open file (it's never saved unless you press mod+s yourself).")
        focused += keystrokes()
    if 3 in picks:
        text = ask("    Text to type (\\n = new line)", "TODO: check the login flow\\n")
        scratch = [{"type": text.replace("\\n", "\n")}, {"wait": "3s"}]

    entries = []
    base = {"app": kind}
    if folder:
        base["folder"] = folder
    if focused or not scratch:
        e = dict(base)
        if focused:
            e["typing_target"] = "focused"
            e["steps"] = focused
        entries.append(e)
    if scratch:
        entries.append({**base, "steps": scratch})
    return entries


def ask_apps(old, has_web):
    olda = old.get("apps") if isinstance(old.get("apps"), dict) else {}
    old_list = [e for e in (olda.get("list") or []) if isinstance(e, dict)]
    if not yes("Switch to a code editor or another app now and then?", bool(old_list) or not old):
        return None
    if old_list:
        names = ", ".join(str(e.get("name") or EDITORS.get(str(e.get("app")), e.get("app"))) for e in old_list)
        keep = yes(f"Keep the current app settings ({names})?", True)
    else:
        keep = False
    if keep:
        items = old_list
    else:
        print("  Which ones?")
        picks = choose_many("Pick one or more (like 1,2)", ["VS Code", "Cursor", "Another app"], "1")
        items = []
        if 1 in picks:
            items += ask_editor("vscode", old_list)
        if 2 in picks:
            items += ask_editor("cursor", old_list)
        if 3 in picks:
            while True:
                print("  Another app:")
                nm = ask("    Its name (for the report)", "My app")
                if sys.platform == "darwin":
                    mac = ask("    Its name in the Applications folder (e.g. Notes, Slack)", nm)
                    e = {"app": "custom", "name": nm, "mac_app": mac}
                else:
                    cmd = ask("    Command that starts it (e.g. notepad, slack, gedit)")
                    title = ask("    Text that appears in its window title", nm)
                    e = {"app": "custom", "name": nm, "command": cmd, "window_title": title}
                if yes("    Send keystrokes to it?", False):
                    e["typing_target"] = "focused"
                    e["steps"] = keystrokes()
                items.append(e)
                if not yes("  Add another app?", False):
                    break
    apps = {"list": items}
    if has_web:
        apps["every"] = number("Switch to an app after every how many website pages?", olda.get("every", 3))
    apps["stay"] = duration("How long to stay in each app?", olda.get("stay", "40s"))
    return apps


# --------------------------------------------------------------------------

def run_wizard(name=None, edit=False):
    """Create (or edit) a setup. Returns the setup name, or None."""
    old = {}
    if edit:
        name = name or store.last_used()
        if not name or not store.path_for(name).exists():
            print(f"No setup called '{name}'." if name else "No saved setup yet.")
            return None
        old = store.read_raw(store.path_for(name))
        print(f"Changing setup '{name}'. Press Enter to keep the value shown in [brackets].")
    else:
        print("Let's set up an automation. Press Enter to accept the value in [brackets].")
        print("Stop at any time with Ctrl+C (nothing is saved until the end).\n")
        while True:
            name = store.slug(ask("Name for this setup", name or ("my-setup" if not store.list_setups() else "")))
            if not store.path_for(name).exists():
                break
            if yes(f"A setup called '{name}' exists. Change that one instead?", True):
                old = store.read_raw(store.path_for(name))
                break

    total = 4
    section(1, total, "General")
    raw = ask_general(old)

    section(2, total, "Website")
    web = ask_website(name, old)
    if web:
        raw["browser"] = web

    section(3, total, "Code editors and apps")
    apps = ask_apps(old, bool(web))
    if apps:
        raw["apps"] = apps

    if not web and not apps:
        print("\nNothing to automate (no website and no app), so nothing was saved.")
        return None

    section(4, total, "Save")
    from .config import normalize
    try:
        normalize(raw)
    except ConfigError as e:
        print(f"Something doesn't fit: {e}\nNothing saved; run 'autopilot setup' again.")
        return None
    path = store.write(name, raw)
    store.set_last_used(name)
    print(f"Saved setup '{name}': {store.summary(raw)}")
    print(f"  ({path})")
    print("From now on, just run:  autopilot        (or: autopilot run " + name + ")")
    return name
