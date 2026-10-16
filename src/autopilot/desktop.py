"""Everything that touches the real desktop: the mouse cursor, the keyboard,
bringing windows to the front and opening apps. Works on Windows, macOS and
Linux (X11). On Linux Wayland sessions these features are switched off."""
import ctypes
import ctypes.util
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

SYSTEM = platform.system()          # "Windows", "Darwin", "Linux"
WINDOWS = SYSTEM == "Windows"
MAC = SYSTEM == "Darwin"
LINUX = SYSTEM == "Linux"

SCRATCH = Path.home() / ".autopilot" / "scratch.txt"


def os_name():
    return {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(SYSTEM, SYSTEM)


def is_wayland():
    return LINUX and (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                      or (bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("DISPLAY")))


# --------------------------------------------------------------------------
# pyautogui, imported carefully
# --------------------------------------------------------------------------

def _import_pyautogui():
    if WINDOWS:
        # Real pixel coordinates even with 125%/150% display scaling.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    if LINUX:
        # pyautogui exits the whole program if tkinter is missing (it only needs
        # it for an optional helper window), so stand in a placeholder.
        try:
            import tkinter  # noqa: F401
        except Exception:
            sys.modules.setdefault("mouseinfo", types.ModuleType("mouseinfo"))
    try:
        import pyautogui
        pyautogui.FAILSAFE = False     # stop from the terminal with Ctrl+C
        pyautogui.PAUSE = 0
        pyautogui.position()           # fails early if there's no usable display
        return pyautogui, None
    except SystemExit as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


class Desktop:
    def __init__(self):
        self.reason = None
        self.pg = None
        if is_wayland():
            self.reason = ("this Linux session uses Wayland, which doesn't let programs move the mouse or "
                           "switch windows. Log out and pick 'Ubuntu on Xorg' (or your desktop's 'Xorg' / "
                           "'X11' option) on the login screen to enable these.")
        elif LINUX and not os.environ.get("DISPLAY"):
            self.reason = "no graphical display found (DISPLAY isn't set)."
        else:
            self.pg, err = _import_pyautogui()
            if not self.pg:
                self.reason = f"pyautogui couldn't start ({err}). Run setup again."
        self._mac_warned = False

    @property
    def ok(self):
        return self.pg is not None

    # ---- coordinates ------------------------------------------------------

    def css_scale(self, device_pixel_ratio):
        """Factor from browser CSS pixels to the coordinates pyautogui uses.
        macOS works in points (same as CSS pixels at 100% zoom); Windows and
        Linux work in real pixels."""
        return 1.0 if MAC else float(device_pixel_ratio or 1)

    def position(self):
        return tuple(self.pg.position())

    def move(self, x, y):
        self.pg.moveTo(int(round(x)), int(round(y)), _pause=False)

    def screen_size(self):
        return tuple(self.pg.size())

    # ---- keyboard / wheel --------------------------------------------------

    def press(self, combo):
        keys = desktop_keys(combo)
        if len(keys) == 1:
            self.pg.press(keys[0])
        else:
            self.pg.hotkey(*keys)

    def type_text(self, text, delay_ms):
        skipped = "".join(ch for ch in text if ord(ch) > 126 and ch not in "\n\t")
        if skipped:
            print(f"   note: can't type non-English characters in desktop apps; skipping {skipped!r}")
        clean = "".join(ch for ch in text if ord(ch) <= 126 or ch in "\n\t")
        self.pg.write(clean, interval=delay_ms / 1000)

    def wheel(self, notches):
        """Scroll the mouse wheel: positive = up, negative = down."""
        if WINDOWS:
            self.pg.scroll(int(notches * 120))   # Windows counts 120 per notch
        elif MAC:
            self.pg.scroll(int(notches * 3))     # macOS counts lines
        else:
            self.pg.scroll(int(notches))

    # ---- windows -----------------------------------------------------------

    def focus(self, spec):
        """Bring a window to the front. `spec` is a WindowSpec. Returns its
        rectangle (left, top, width, height) or None if not found."""
        try:
            if WINDOWS:
                return self._focus_windows(spec)
            if MAC:
                return self._focus_mac(spec)
            return self._focus_linux(spec)
        except Exception:
            return None

    def _focus_windows(self, spec):
        try:
            import pygetwindow as gw
        except Exception:
            return None
        wins = [w for w in gw.getAllWindows() if w.title and spec.matches(w.title)]
        wins.sort(key=lambda w: spec.score(w.title), reverse=True)
        for w in wins:
            try:
                if w.isMinimized:
                    w.restore()
                self.pg.press("alt")      # lets Windows hand focus to another app
                ctypes.windll.user32.SetForegroundWindow(w._hWnd)
            except Exception:
                pass
            time.sleep(0.5)
            return (w.left, w.top, w.width, w.height)
        return None

    def _osascript(self, script):
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()

    def _focus_mac(self, spec):
        if not spec.mac_app:
            return None
        code, out, _ = self._osascript(f'application "{spec.mac_app}" is running')
        if out != "true":
            return None
        self._osascript(f'tell application "{spec.mac_app}" to activate')
        time.sleep(0.6)
        proc = spec.mac_process or spec.mac_app
        code, out, err = self._osascript(
            f'tell application "System Events" to tell process "{proc}" to '
            f'get {{position, size}} of front window')
        nums = [int(float(n)) for n in re.findall(r"-?\d+(?:\.\d+)?", out)]
        if code == 0 and len(nums) == 4:
            return tuple(nums)
        if "not allowed" in err.lower() or "assistive" in err.lower():
            if not self._mac_warned:
                print("   macOS: allow your Terminal app under System Settings > Privacy & Security > "
                      "Accessibility, then restart the run.")
                self._mac_warned = True
        w, h = self.screen_size()
        return (0, 25, w, h - 25)

    def _focus_linux(self, spec):
        if shutil.which("wmctrl"):
            r = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True, timeout=5)
            rows = []
            for line in r.stdout.splitlines():
                parts = line.split(None, 7)
                if len(parts) < 8:
                    continue
                wid, _desk, x, y, w, h, _host, title = parts
                if spec.matches(title):
                    rows.append((spec.score(title), wid, int(x), int(y), int(w), int(h)))
            if not rows:
                return None
            rows.sort(reverse=True)
            _, wid, x, y, w, h = rows[0]
            subprocess.run(["wmctrl", "-i", "-a", wid], timeout=5)
            time.sleep(0.5)
            return (x, y, w, h)
        if shutil.which("xdotool"):
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", spec.pattern()],
                               capture_output=True, text=True, timeout=5)
            ids = r.stdout.split()
            if not ids:
                return None
            wid = ids[-1]
            subprocess.run(["xdotool", "windowactivate", wid], timeout=5)
            g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                               capture_output=True, text=True, timeout=5).stdout
            vals = dict(line.split("=", 1) for line in g.splitlines() if "=" in line)
            time.sleep(0.5)
            return (int(vals.get("X", 0)), int(vals.get("Y", 0)),
                    int(vals.get("WIDTH", 800)), int(vals.get("HEIGHT", 600)))
        return None


class WindowSpec:
    """How to recognise a window: title contains/ends with text, plus the
    macOS application name."""

    def __init__(self, contains=(), endswith=None, prefer=None, mac_app=None, mac_process=None):
        self.contains = [c for c in contains if c]
        self.endswith = endswith
        self.prefer = prefer          # extra text that makes a window a better match
        self.mac_app = mac_app
        self.mac_process = mac_process

    def matches(self, title):
        t = title.strip()
        if self.endswith and not t.endswith(self.endswith):
            return False
        return all(c in t for c in self.contains)

    def score(self, title):
        return 1 if self.prefer and self.prefer.lower() in title.lower() else 0

    def pattern(self):
        bits = [re.escape(c) for c in self.contains]
        if self.endswith:
            bits.append(re.escape(self.endswith) + "$")
        return ".*".join(bits) or "."


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------

_KEY_ALIASES = {
    "return": "enter", "escape": "esc", "control": "ctrl", "cmd": "command", "meta": "command",
    "super": "win", "windows": "win", "option": "alt", "opt": "alt", "del": "delete",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "pgup": "pageup", "pgdn": "pagedown", "spacebar": "space",
}


def _split_combo(combo):
    combo = str(combo).strip()
    if combo == "+":
        return ["+"]
    return [p.strip() for p in re.split(r"\+(?!$)", combo) if p.strip()]


def desktop_keys(combo):
    keys = []
    for k in _split_combo(combo):
        k = k.lower()
        k = _KEY_ALIASES.get(k, k)
        if k == "mod":
            k = "command" if MAC else "ctrl"
        if k == "command" and not MAC:
            k = "ctrl"
        keys.append(k)
    return keys


_PW_NAMES = {
    "enter": "Enter", "esc": "Escape", "tab": "Tab", "space": "Space", "backspace": "Backspace",
    "delete": "Delete", "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown", "ctrl": "Control",
    "shift": "Shift", "alt": "Alt", "command": "Meta", "win": "Meta", "insert": "Insert",
}


def browser_key(combo):
    out = []
    for k in _split_combo(combo):
        low = _KEY_ALIASES.get(k.lower(), k.lower())
        if low == "mod" or (low == "command" and not MAC):
            out.append("Meta" if MAC else "Control")
        elif low in _PW_NAMES:
            out.append(_PW_NAMES[low])
        elif re.fullmatch(r"f\d{1,2}", low):
            out.append(low.upper())
        elif len(k) == 1:
            out.append(k)
        else:
            out.append(k[0].upper() + k[1:])
    return "+".join(out)


# --------------------------------------------------------------------------
# Opening apps
# --------------------------------------------------------------------------

APP_PRESETS = {
    "vscode": {
        "title_suffix": "Visual Studio Code",
        "mac_app": "Visual Studio Code",
        "mac_process": "Code",
        "cli": "code",
        "win_paths": [r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd",
                      r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd"],
    },
    "cursor": {
        "title_suffix": "Cursor",
        "mac_app": "Cursor",
        "mac_process": "Cursor",
        "cli": "cursor",
        "win_paths": [r"%LOCALAPPDATA%\Programs\cursor\resources\app\bin\cursor.cmd",
                      r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"],
    },
}


def window_spec_for_app(app):
    if app["app"] in APP_PRESETS:
        p = APP_PRESETS[app["app"]]
        prefer = Path(app["folder"]).name if app.get("folder") else None
        return WindowSpec(endswith=p["title_suffix"], prefer=prefer,
                          mac_app=app.get("mac_app") or p["mac_app"], mac_process=p["mac_process"])
    title = app.get("window_title") or ""
    return WindowSpec(contains=[title] if title else [], mac_app=app.get("mac_app") or title or None)


def app_launcher(app):
    """The command list that opens the app, or None if it can't be found."""
    if app["app"] in APP_PRESETS:
        p = APP_PRESETS[app["app"]]
        cli = shutil.which(p["cli"])
        if cli:
            return [cli]
        if WINDOWS:
            for raw in p["win_paths"]:
                path = os.path.expandvars(raw)
                if os.path.isfile(path):
                    return [path]
        if MAC and Path(f"/Applications/{p['mac_app']}.app").exists():
            return ["open", "-a", p["mac_app"]]
        return None
    if app.get("command"):
        import shlex
        return shlex.split(app["command"], posix=not WINDOWS)
    if MAC and app.get("mac_app"):
        return ["open", "-a", app["mac_app"]]
    return None


def launch(app, target=None, reuse_window=False):
    """Open the app, optionally on a folder or file."""
    cmd = app_launcher(app)
    if not cmd:
        raise RuntimeError(f"couldn't find how to open {app['name']}. "
                           + ("Install it, or in VS Code / Cursor run 'Shell Command: Install command in PATH'."
                              if app["app"] in APP_PRESETS else "Check its 'command:' setting."))
    args = list(cmd)
    is_editor_cli = app["app"] in APP_PRESETS and args[0] != "open"
    if reuse_window and is_editor_cli:
        args.append("-r")
    if target:
        args.append(str(target))
    subprocess.Popen(args, shell=WINDOWS and args[0].lower().endswith(".cmd"),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def app_installed(app):
    return app_launcher(app) is not None
