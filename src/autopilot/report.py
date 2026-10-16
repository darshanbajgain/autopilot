"""Per-visit log lines and the end-of-run summary."""
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from .config import fmt_duration


class Report:
    def __init__(self, log):
        self.log = log
        self.rows = []
        self.started = time.time()
        self.stop_reason = ""

    def add(self, kind, name, ok, secs, notes=None, console_errors=0, checks=None):
        notes = [n for n in (notes or []) if n]
        checks = checks or []
        failed_checks = [c for c in checks if not c[1]]
        ok = ok and not failed_checks
        self.rows.append({"kind": kind, "name": name, "ok": ok, "secs": secs, "notes": notes,
                          "errors": console_errors, "checks": checks})
        extra = []
        if console_errors:
            extra.append(f"{console_errors} console error(s)")
        for text, passed in checks:
            extra.append(f"check '{text}': {'ok' if passed else 'NOT FOUND'}")
        extra += notes
        label = "PASS" if ok else "FAIL"
        icon = "web " if kind == "page" else "app "
        self.log(f"  {label}  {icon}{name:<22} {secs:6.1f}s  {'  |  '.join(extra)}")

    def summary(self, reports_dir):
        lines = []
        total = time.time() - self.started
        passed = sum(r["ok"] for r in self.rows)
        failed = len(self.rows) - passed
        lines.append("=" * 72)
        lines.append(f"Run finished: {self.stop_reason or 'done'}")
        lines.append(f"Ran for {fmt_duration(total)}; {len(self.rows)} visits, {passed} passed, {failed} failed.")
        if self.rows:
            lines.append("")
            lines.append(f"{'':2}{'Where':<28}{'Visits':>7}{'Failed':>8}{'Avg time':>10}{'Console err':>13}")
            groups = OrderedDict()
            for r in self.rows:
                key = ("web " if r["kind"] == "page" else "app ") + r["name"]
                g = groups.setdefault(key, {"n": 0, "fail": 0, "secs": 0.0, "err": 0, "notes": []})
                g["n"] += 1
                g["fail"] += 0 if r["ok"] else 1
                g["secs"] += r["secs"]
                g["err"] += r["errors"]
                for n in r["notes"] + [f"check '{c[0]}' not found" for c in r["checks"] if not c[1]]:
                    if n not in g["notes"]:
                        g["notes"].append(n)
            for key, g in groups.items():
                mark = "  " if not g["fail"] else "! "
                lines.append(f"{mark}{key[:27]:<28}{g['n']:>7}{g['fail']:>8}"
                             f"{g['secs'] / g['n']:>9.1f}s{g['err']:>13}")
            problems = [(k, g["notes"]) for k, g in groups.items() if g["notes"]]
            if problems:
                lines.append("")
                lines.append("Problems seen:")
                for k, notes in problems:
                    for n in notes[:5]:
                        lines.append(f"  - {k}: {n}")
        lines.append("=" * 72)
        text = "\n".join(lines)
        self.log("\n" + text)
        try:
            Path(reports_dir).mkdir(parents=True, exist_ok=True)
            out = Path(reports_dir) / f"run-{datetime.now():%Y%m%d-%H%M%S}.txt"
            out.write_text(text + "\n", encoding="utf-8")
            self.log(f"Saved to {out}")
        except Exception:
            pass
        return failed == 0
