"""Desktop apps (VS Code, Cursor, anything else): bring to front or open,
run keystroke steps, then wander and scroll in the window."""
import random
import time
from pathlib import Path

from .desktop import SCRATCH, app_installed, launch, window_spec_for_app


class AppVisitor:
    def __init__(self, ctx):
        self.ctx = ctx
        self.opened_folder = set()

    def _wait_for_window(self, spec, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rect = self.ctx.desktop.focus(spec)
            if rect:
                self.ctx.human.script_acted()
                return rect
            time.sleep(0.5)
        return None

    def bring_up(self, app):
        """Focus the app's window, opening it (on its folder) if needed."""
        spec = window_spec_for_app(app)
        rect = self.ctx.desktop.focus(spec)
        folder = app.get("folder")
        # Open it on its folder the first time (this also just focuses the
        # window if that folder is already open), or if it isn't running.
        if not rect or (folder and app["name"] not in self.opened_folder):
            if folder and not Path(folder).exists():
                raise RuntimeError(f"folder not found: {folder}")
            self.ctx.log(f"   opening {app['name']}" + (f" on {folder}" if folder else "") + " ...")
            launch(app, folder)
            if folder:
                self.opened_folder.add(app["name"])
            rect = self._wait_for_window(spec, 25)
        if not rect:
            raise RuntimeError(f"couldn't find the {app['name']} window after opening it.")
        self.ctx.human.script_acted()
        return spec, rect

    def visit(self, app, seconds):
        ctx = self.ctx
        spec, rect = self.bring_up(app)
        refocus = lambda: ctx.desktop.focus(spec)
        ctx.human.on_resume = refocus

        steps = app["steps"]
        types_text = any(s["action"] == "type" for s in steps)
        use_scratch = app["typing_target"] == "scratch" and types_text
        if steps:
            if use_scratch:
                self._open_scratch(app, spec)
            try:
                self._run_steps(steps)
            finally:
                if use_scratch:
                    self._clean_scratch(app, spec)
            refocus()

        # The rest of the time: wander and scroll inside the window.
        end = ctx.active_deadline(seconds)
        down = True
        moves = 0
        while not ctx.passed(end):
            ctx.human.check()
            if ctx.cursor_on:
                left, top, w, h = rect
                x = left + random.uniform(0.25, 0.85) * w
                y = top + random.uniform(0.25, 0.85) * h
                ctx.human.glide(x, y, ctx.t["cursor_move"] * random.uniform(0.8, 1.5))
                ctx.human.check()
                ctx.desktop.wheel((-1 if down else 1) * random.randint(2, 4))
                ctx.human.script_acted()
                moves += 1
                if moves % 5 == 0:
                    down = not down
            ctx.sleep(random.uniform(ctx.t["gap_min"], ctx.t["gap_max"]))

    def _open_scratch(self, app, spec):
        SCRATCH.parent.mkdir(parents=True, exist_ok=True)
        if not SCRATCH.exists():
            SCRATCH.write_text("", encoding="utf-8")
        launch(app, SCRATCH, reuse_window=True)
        time.sleep(1.5)
        self._wait_for_window(spec, 10)
        time.sleep(0.5)

    def _clean_scratch(self, app, spec):
        """Empty and save the scratch file so it never grows or nags."""
        try:
            launch(app, SCRATCH, reuse_window=True)
            time.sleep(1.5)
            self._wait_for_window(spec, 10)
            d = self.ctx.desktop
            d.press("mod+a")
            d.press("backspace")
            d.press("mod+s")
            self.ctx.human.script_acted()
            time.sleep(0.5)
        except Exception:
            pass

    def _run_steps(self, steps):
        ctx = self.ctx
        d = ctx.desktop
        for s in steps:
            ctx.raise_if_out_of_time()
            act, val = s["action"], s["value"]
            ctx.human.check()
            if act == "press":
                d.press(val)
                ctx.human.script_acted()
                ctx.sleep(0.4)
            elif act == "type":
                d.type_text(val, ctx.t["typing_delay"])
                ctx.human.script_acted()
                ctx.sleep(0.3)
            elif act == "wait":
                ctx.sleep(val)
            elif act == "scroll":
                notches = {"down": -5, "up": 5, "bottom": -60, "top": 60}[val]
                d.wheel(notches)
                ctx.human.script_acted()
                ctx.sleep(0.5)
            elif act == "wander":
                end = ctx.active_deadline(val)
                while not ctx.passed(end):
                    w, h = d.screen_size()
                    ctx.human.glide(random.uniform(0.2, 0.8) * w, random.uniform(0.2, 0.8) * h,
                                    ctx.t["cursor_move"])
                    ctx.sleep(random.uniform(ctx.t["gap_min"], ctx.t["gap_max"]))


def check_app(app):
    problems = []
    if not app_installed(app):
        problems.append(f"can't find how to open {app['name']}"
                        + (" (in VS Code / Cursor run 'Shell Command: Install command in PATH')"
                           if app["app"] != "custom" else " (check 'command:')"))
    if app.get("folder") and not Path(app["folder"]).exists():
        problems.append(f"folder not found: {app['folder']}")
    return problems
