"""Command-line entry point: autopilot (menu) | setup | edit | run | check | list | delete | doctor | forget."""
import argparse
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__, store
from .config import ConfigError, SPEEDS, fmt_duration, load, parse_duration


def _apply_overrides(cfg, args):
    if getattr(args, "run_for", None):
        cfg["run_for"] = parse_duration(args.run_for, "--run-for", allow_forever=True)
    if getattr(args, "speed", None):
        cfg["speed"] = args.speed
        cfg["tuning"] = dict(SPEEDS[args.speed])
    if getattr(args, "no_cursor", False):
        cfg["real_cursor"] = False
    if getattr(args, "no_pause", False):
        cfg["pause_when_touched"] = False
    if cfg.get("browser"):
        if getattr(args, "stay", None):
            cfg["browser"]["stay_on_page"] = parse_duration(args.stay, "--stay")
        if getattr(args, "headless", False):
            cfg["browser"]["headless"] = True
            cfg["real_cursor"] = False
        if getattr(args, "attach", False):
            cfg["browser"]["attach"] = True
    return cfg


def _load_setup(arg):
    path = store.resolve(arg)
    if path.parent == store.setups_dir():
        store.set_last_used(path.stem)
    return path, load(path)


def start_run(arg=None, args=None):
    from .runner import run
    path, cfg = _load_setup(arg)
    print(f"Setup: {path.stem}  ({path})")
    cfg = _apply_overrides(cfg, args or argparse.Namespace())
    return run(cfg, countdown=5)


def cmd_run(args):
    sys.exit(0 if start_run(args.setup, args) else 1)


def _offer_run(name):
    from .wizard import yes
    if name and yes("\nRun it now?", True):
        start_run(name)


def cmd_setup(args):
    from .wizard import run_wizard
    _offer_run(run_wizard(args.name))


def cmd_edit(args):
    from .wizard import run_wizard
    _offer_run(run_wizard(args.name, edit=True))


def cmd_list(args):
    names = store.list_setups()
    if not names:
        print("No saved setups yet. Create one with:  autopilot setup")
        return
    last = store.last_used()
    print(f"Saved setups (in {store.setups_dir()}):")
    for n in names:
        mark = "*" if n == last else " "
        print(f" {mark} {n:<20} {store.summary(store.read_raw(store.path_for(n)))}")
    print("\n* = used by 'autopilot run' with no name")


def cmd_delete(args):
    from .wizard import yes
    p = store.path_for(args.name)
    if not p.exists():
        print(f"No setup called '{args.name}'.")
        return
    if yes(f"Delete setup '{p.stem}'?", False):
        p.unlink()
        env = p.with_suffix(".env")
        if env.exists():
            env.unlink()
        print("Deleted. (A saved login stays in the password store; remove it with 'autopilot forget <site>'.)")


def menu():
    """'autopilot' with nothing else: pick a saved setup and what to do with it."""
    from .wizard import ask, choose, run_wizard
    print(f"Autopilot {__version__}\n")
    if not store.list_setups():
        print("No saved setup yet - let's create your first one.\n")
        _offer_run(run_wizard())
        return
    current = store.last_used()
    while True:
        names = store.list_setups()
        if current not in names:
            current = names[0] if names else None
        if not current:
            _offer_run(run_wizard())
            return
        raw = store.read_raw(store.path_for(current))
        print(f"Setup: {current}  -  {store.summary(raw)}")
        opts = ["Run it", "Change its settings", "Test it (no clicking or typing)", "Create a new setup"]
        if len(names) > 1:
            opts.append(f"Use another setup ({len(names) - 1} more)")
        opts.append("Quit")
        n = choose("Choose", opts, 1)
        pick = opts[n - 1]
        if pick == "Run it":
            start_run(current)
            return
        if pick == "Change its settings":
            _offer_run(run_wizard(current, edit=True))
            return
        if pick.startswith("Test it"):
            try:
                run_check(store.path_for(current), argparse.Namespace(show=True))
            except SystemExit:
                pass
            print()
        elif pick == "Create a new setup":
            _offer_run(run_wizard())
            return
        elif pick.startswith("Use another"):
            print()
            for i, nm in enumerate(names, 1):
                print(f"    {i}) {nm:<20} {store.summary(store.read_raw(store.path_for(nm)))}")
            while True:
                a = ask("  Which one", "1")
                if a.isdigit() and 1 <= int(a) <= len(names):
                    current = names[int(a) - 1]
                    store.set_last_used(current)
                    break
            print()
        else:
            return


def cmd_forget(args):
    from .creds import forget
    target = args.site
    try:
        setup_path = store.resolve(target) if "://" not in target else None
    except RuntimeError:
        setup_path = None
    if setup_path:
        cfg = load(setup_path)
        if not cfg.get("browser"):
            print("That settings file has no website.")
            return
        target = cfg["browser"]["site"]
    ok, msg = forget(target)
    print(msg)


def cmd_check(args):
    path, _ = _load_setup(args.setup)
    sys.exit(0 if run_check(path, args) == 0 else 1)


def run_check(path, args):
    """Validate the settings and try everything without clicking or typing."""
    from .apps import check_app
    from .runner import Context, describe, find_running_browser

    cfg = _apply_overrides(load(path), args)
    print(f"Settings OK: {path}\n")
    cfg["pause_when_touched"] = False
    ctx = Context(cfg)
    describe(cfg, ctx)
    problems = 0

    if cfg["apps"]:
        print("Desktop apps:")
        for app in cfg["apps"]["list"]:
            issues = check_app(app)
            problems += len(issues)
            print(f"  {'!!' if issues else 'ok'} {app['name']}" + ("".join(f"\n       {i}" for i in issues)))
        print()

    b = cfg["browser"]
    if b:
        from playwright.sync_api import sync_playwright
        from .browser import Browser
        from .creds import Credentials
        print("Website:")
        cfg["real_cursor"] = False
        ctx.cursor_on = False
        if not b["attach"] and not args.show:
            b["headless"] = True
        creds = Credentials(b["login"], b["site"], cfg["_path"], print) if b["login"] else None
        with sync_playwright() as p:
            web = Browser(b, ctx)
            try:
                web.start(p, lambda: find_running_browser(b["channel"]))
                state = web.ensure_logged_in(creds)
                print(f"  ok login: {state}")
                pages = web.discover_pages()
                if not pages:
                    problems += 1
                    print("  !! no pages found. List them under 'pages:' or set 'nav_area:'.")
                else:
                    where = f" (menu found in '{web.nav_area}')" if web.nav_area else ""
                    print(f"  ok found {len(pages)} page(s){where}: {', '.join(p_.label for p_ in pages)}")
                for ref in pages:
                    try:
                        web.open_page(ref)
                        web.settle()
                        line = f"  ok {ref.label:<22} {web.page.url}"
                        if web.errors:
                            line += f"   ({len(web.errors)} console error(s))"
                        web.errors.clear()
                        print(line)
                    except Exception as e:
                        problems += 1
                        print(f"  !! {ref.label:<22} {str(e).splitlines()[0][:100]}")
                        continue
                    for action in web.actions_for(ref):
                        for s in action["steps"]:
                            target = s.get("into") or (s["value"] if s["action"] == "click" else None)
                            if not target:
                                continue
                            kind = "field" if s.get("into") else "click"
                            found = web.resolve(target, kind, timeout=3) is not None
                            mark = "ok" if found else "??"
                            note = "" if found else "  (not visible now; fine if an earlier step makes it appear)"
                            print(f"       {mark} {s['action']} '{target}'{note}")
                unmatched = [x["page"] for x in b["actions"] if x["page"] != "*" and
                             not any(x["page"].lower() in r.label.lower() for r in pages)]
                for u in unmatched:
                    problems += 1
                    print(f"  !! action page '{u}' doesn't match any page name")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                problems += 1
                print(f"  !! {str(e).splitlines()[0]}")
            finally:
                web.close()
        print()
    print("All good." if not problems else f"{problems} problem(s) to look at (marked !!).")
    return problems


def cmd_doctor(args):
    """Check this computer is ready."""
    from .desktop import Desktop, MAC, LINUX, WINDOWS, is_wayland, os_name
    from .creds import _keyring
    from .runner import find_running_browser

    def line(ok, text, tip=None):
        print(f"  {'ok' if ok else '!!'} {text}" + (f"\n       -> {tip}" if tip and not ok else ""))

    print(f"Autopilot {__version__} on {os_name()} ({platform.release()}), Python {platform.python_version()}\n")
    line(sys.version_info >= (3, 9), "Python 3.9 or newer", "Install a newer Python from python.org")
    try:
        import playwright  # noqa: F401
        line(True, "Playwright installed")
    except Exception:
        line(False, "Playwright installed", "Run setup again")

    chrome = None
    if WINDOWS:
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            pth = Path(base) / "Google/Chrome/Application/chrome.exe"
            if base and pth.exists():
                chrome = pth
    elif MAC:
        pth = Path("/Applications/Google Chrome.app")
        chrome = pth if pth.exists() else None
    else:
        chrome = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
                  or (Path("/opt/google/chrome/chrome").exists() and "/opt/google/chrome/chrome"))
    line(bool(chrome), "Google Chrome found",
         "Install Chrome, or use 'channel: chromium' and run: python -m playwright install chromium")

    ep = find_running_browser("chrome")
    line(ep.startswith("ws://"), "Your open Chrome allows 'attach' (remote debugging on)",
         "Only needed for 'attach: yes'. In Chrome open chrome://inspect/#remote-debugging and turn it on.")

    if is_wayland():
        line(False, "Desktop control (cursor, apps, pause-on-touch)",
             "Wayland session. Log out and choose 'Ubuntu on Xorg' (or Xorg/X11) on the login screen.")
    else:
        d = Desktop()
        line(d.ok, "Desktop control (cursor, apps, pause-on-touch)", d.reason)
        if d.ok:
            from .human import _idle_reader
            line(_idle_reader() is not None, "Can notice keyboard use (for pause-on-touch)",
                 "Linux: install libxss1 or xprintidle. Without it, only mouse movement pauses the run.")
    if LINUX and not is_wayland():
        line(bool(shutil.which("wmctrl") or shutil.which("xdotool")), "Window switching tool (wmctrl)",
             "sudo apt install wmctrl   (or your distro's equivalent)")
    if MAC:
        print("  -- macOS: allow your Terminal app in System Settings > Privacy & Security > Accessibility")
        print("     (needed to move the mouse, type and switch apps).")
    line(_keyring() is not None, "Password store available (for 'saved' logins)",
         "Optional. Use 'credentials: ask' or 'env' instead.")
    for cli in ("code", "cursor"):
        print(f"  {'ok' if shutil.which(cli) else '--'} '{cli}' command "
              f"{'found' if shutil.which(cli) else 'not on PATH (only needed for that editor)'}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="autopilot",
        description="Automate a website and your desktop apps from a settings file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Just run 'autopilot' for the menu.\nFirst time: autopilot setup     Full guide: README.md")
    ap.add_argument("--version", action="version", version=f"autopilot {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")

    for alias in ("setup", "init"):
        p = sub.add_parser(alias, help="create a setup by answering questions" if alias == "setup"
                           else argparse.SUPPRESS)
        p.add_argument("name", nargs="?", help="name for the setup")
        p.set_defaults(func=cmd_setup)
    p = sub.add_parser("edit", help="change a saved setup (default: the last used)")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_edit)
    p = sub.add_parser("list", help="list saved setups")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("delete", help="delete a saved setup")
    p.add_argument("name")
    p.set_defaults(func=cmd_delete)

    for name, func, helptext in (("run", cmd_run, "run an automation"),
                                 ("check", cmd_check, "test a settings file without clicking or typing")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("setup", nargs="?", help="setup name or .yaml file (default: the last used)")
        p.add_argument("--speed", choices=list(SPEEDS), help="override the speed")
        p.add_argument("--stay", help="override time on each page, e.g. 45s")
        p.add_argument("--attach", action="store_true", help="use the browser you already have open")
        p.add_argument("--headless", action="store_true", help="no browser window (no cursor)")
        if name == "run":
            p.add_argument("--run-for", help="override how long to run: 30m, 2h, forever")
            p.add_argument("--no-cursor", action="store_true", help="don't move the real mouse")
            p.add_argument("--no-pause", action="store_true", help="don't pause when you touch the mouse")
        else:
            p.add_argument("--show", action="store_true", help="show the browser window while checking")
        p.set_defaults(func=func)

    p = sub.add_parser("doctor", help="check this computer is ready")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("forget", help="remove a saved login")
    p.add_argument("site", help="the site address (or a settings file)")
    p.set_defaults(func=cmd_forget)

    args = ap.parse_args(argv)
    try:
        if not getattr(args, "func", None):
            menu()
            return
        args.func(args)
    except ConfigError as e:
        print(f"Problem in the settings file:\n  {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        log = store.home() / "last-error.txt"
        try:
            log.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        first = (str(e).strip().splitlines() or [type(e).__name__])[0]
        print(f"\nError: {type(e).__name__}: {first[:200]}")
        print(f"Full details saved to {log} - send that file if you need help.")
        sys.exit(1)
