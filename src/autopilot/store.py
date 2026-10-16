"""Where saved setups live: <home>/.autopilot/setups/<name>.yaml, plus a
note of which one was used last."""
import json
import os
import re
from pathlib import Path

import yaml


def home():
    d = Path(os.environ.get("AUTOPILOT_HOME") or (Path.home() / ".autopilot"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def setups_dir():
    d = home() / "setups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(name):
    s = re.sub(r"[^\w\-]+", "-", str(name).strip().lower()).strip("-")
    return s or "my-setup"


def path_for(name):
    return setups_dir() / f"{slug(name)}.yaml"


def list_setups():
    files = sorted(setups_dir().glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files]


def _state_file():
    return home() / "state.json"


def last_used():
    try:
        name = json.loads(_state_file().read_text(encoding="utf-8")).get("last")
    except Exception:
        name = None
    if name and path_for(name).exists():
        return name
    names = list_setups()
    return names[0] if names else None


def set_last_used(name):
    try:
        _state_file().write_text(json.dumps({"last": slug(name)}), encoding="utf-8")
    except Exception:
        pass


def resolve(arg):
    """A setup name, a path to a .yaml file, or None for the last used one.
    Returns a Path, or raises RuntimeError with a helpful message."""
    if arg:
        p = Path(arg).expanduser()
        if p.suffix in (".yaml", ".yml") and p.is_file():
            return p
        if path_for(arg).exists():
            return path_for(arg)
        names = list_setups()
        hint = f" Saved setups: {', '.join(names)}." if names else " Create one with:  autopilot setup"
        raise RuntimeError(f"no setup or file called '{arg}'.{hint}")
    name = last_used()
    if not name:
        raise RuntimeError("no saved setup yet. Create one with:  autopilot setup")
    return path_for(name)


def read_raw(path):
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


HEADER = """# Autopilot setup: {name}
# Made with 'autopilot setup'. Change it with:  autopilot edit {name}
# (or edit this file by hand - every option is explained in README.md)
"""


def write(name, raw):
    p = path_for(name)
    body = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)
    p.write_text(HEADER.format(name=slug(name)) + "\n" + body, encoding="utf-8")
    return p


def summary(raw):
    """One line describing a setup."""
    bits = []
    b = raw.get("browser") or {}
    if b.get("site"):
        bits.append(re.sub(r"^https?://", "", str(b["site"])).rstrip("/"))
    apps = raw.get("apps") or {}
    names = []
    for a in (apps.get("list") or []) if isinstance(apps, dict) else []:
        if isinstance(a, dict):
            n = a.get("name") or {"vscode": "VS Code", "cursor": "Cursor"}.get(str(a.get("app")), a.get("app"))
            if n and n not in names:
                names.append(str(n))
    if names:
        bits.append(" + ".join(names))
    bits.append(str(raw.get("run_for", "forever")))
    bits.append(str(raw.get("speed", "normal")))
    return ", ".join(bits)
