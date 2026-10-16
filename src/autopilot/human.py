"""Noticing when you use the mouse or keyboard, so the run can pause and
hand control back to you."""
import ctypes
import ctypes.util
import math
import shutil
import subprocess
import time

from .desktop import LINUX, MAC, WINDOWS


def _idle_reader():
    """A function returning seconds since the last mouse/keyboard input on this
    computer (any app), or None if this system can't tell."""
    if WINDOWS:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        def read():
            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
            return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
        return read

    if MAC:
        try:
            lib = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            fn = lib.CGEventSourceSecondsSinceLastEventType
            fn.restype = ctypes.c_double
            fn.argtypes = [ctypes.c_int32, ctypes.c_uint32]
            fn(0, 0xFFFFFFFF)
            return lambda: fn(0, 0xFFFFFFFF)   # combined session state, any input event
        except Exception:
            return None

    if LINUX:
        try:
            x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss"))

            class XScreenSaverInfo(ctypes.Structure):
                _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                            ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong),
                            ("eventMask", ctypes.c_ulong)]

            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
            xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                  ctypes.POINTER(XScreenSaverInfo)]
            dpy = x11.XOpenDisplay(None)
            if not dpy:
                raise OSError
            root = x11.XDefaultRootWindow(dpy)
            info = xss.XScreenSaverAllocInfo()

            def read():
                xss.XScreenSaverQueryInfo(dpy, root, info)
                return info.contents.idle / 1000.0
            read()
            return read
        except Exception:
            pass
        if shutil.which("xprintidle"):
            def read():
                out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2).stdout
                return int(out.strip()) / 1000.0
            return read
    return None


class Human:
    """Pauses the run while you're using the computer.

    The script remembers where it last put the cursor and when it last sent
    input. If the cursor is somewhere else, or the system saw input after the
    script's own, that was you."""

    def __init__(self, desktop, enabled, resume_after, log):
        self.desktop = desktop
        self.enabled = enabled and desktop.ok
        self.resume_after = resume_after
        self.log = log
        self.idle = _idle_reader() if self.enabled else None
        self.expected = None
        self.quiet_since = time.monotonic()
        self.paused_total = 0.0
        self.on_resume = None

    @property
    def keyboard_aware(self):
        return self.idle is not None

    def script_acted(self, pos=None):
        """Record that the script itself just moved the mouse / pressed keys."""
        if not self.enabled:
            return
        self.expected = pos or self.desktop.position()
        self.quiet_since = time.monotonic()

    def user_active(self):
        if not self.enabled:
            return False
        if self.expected:
            x, y = self.desktop.position()
            if math.hypot(x - self.expected[0], y - self.expected[1]) > 8:
                return True
        if self.idle:
            try:
                since_script = time.monotonic() - self.quiet_since
                if self.idle() < since_script - 0.15:
                    return True
            except Exception:
                self.idle = None
        return False

    def check(self):
        """If you're using the computer, wait until you've stopped."""
        if not self.user_active():
            return
        self.log(f"\n   [paused] You took over. Resuming after {self.resume_after:.0f}s without "
                 "mouse/keyboard input. (Ctrl+C in this terminal to stop.)")
        start = time.monotonic()
        last_pos, last_move = self.desktop.position(), time.monotonic()
        while True:
            pos = self.desktop.position()
            if pos != last_pos:
                last_pos, last_move = pos, time.monotonic()
            idle = time.monotonic() - last_move
            if self.idle:
                try:
                    idle = min(idle, self.idle())
                except Exception:
                    pass
            if idle >= self.resume_after:
                break
            time.sleep(0.25)
        self.paused_total += time.monotonic() - start
        self.log("   [resumed]")
        if self.on_resume:
            try:
                self.on_resume()
            except Exception:
                pass
        self.script_acted()

    def sleep(self, seconds):
        """Sleep, pausing right away if you start using the computer."""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self.check()
            left = end - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(0.1, left))

    def glide(self, x, y, duration):
        """Glide the real mouse to screen point (x, y)."""
        d = self.desktop
        self.check()
        sx, sy = d.position()
        steps = max(1, int(duration * 60))
        for i in range(1, steps + 1):
            if self.user_active():
                self.check()
                sx, sy = d.position()
            t = i / steps
            t = 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2      # ease in-out
            nx, ny = round(sx + (x - sx) * t), round(sy + (y - sy) * t)
            d.move(nx, ny)
            self.expected = (nx, ny)
            self.quiet_since = time.monotonic()
            time.sleep(duration / steps)
        if self.enabled:
            self.expected = d.position()
