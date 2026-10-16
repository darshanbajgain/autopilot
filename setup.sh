#!/usr/bin/env sh
# Autopilot setup for macOS and Linux. Run from this folder:   sh setup.sh
set -e
cd "$(dirname "$0")"

echo "== Autopilot setup =="

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9 or newer is needed."
  echo "  macOS: install it from https://www.python.org/downloads/ (or: brew install python)"
  echo "  Linux: sudo apt install python3 python3-venv   (or your distro's equivalent)"
  exit 1
fi
echo "Using $($PY --version)"

if [ ! -x .venv/bin/python ]; then
  echo "Creating a private Python environment in .venv ..."
  if ! "$PY" -m venv .venv; then
    echo "Couldn't create it. On Debian/Ubuntu run:  sudo apt install python3-venv   and try again."
    exit 1
  fi
fi

echo "Installing packages (a minute or two) ..."
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

chmod +x autopilot 2>/dev/null || true

# Browser: use Google Chrome if it's installed, otherwise offer Playwright's Chromium.
HAVE_CHROME=no
if [ "$(uname)" = "Darwin" ]; then
  [ -d "/Applications/Google Chrome.app" ] && HAVE_CHROME=yes
else
  command -v google-chrome >/dev/null 2>&1 && HAVE_CHROME=yes
  command -v google-chrome-stable >/dev/null 2>&1 && HAVE_CHROME=yes
  [ -x /opt/google/chrome/chrome ] && HAVE_CHROME=yes
fi
if [ "$HAVE_CHROME" = no ]; then
  echo
  echo "Google Chrome wasn't found."
  printf "Download Playwright's own Chromium instead? (then use 'channel: chromium') [Y/n] "
  read ans || ans=""
  case "$ans" in n|N) ;; *) .venv/bin/python -m playwright install chromium ;; esac
fi

echo
if [ "$(uname)" = "Darwin" ]; then
  echo "macOS: one more step for moving the mouse, typing and switching apps:"
  echo "  System Settings > Privacy & Security > Accessibility > turn on your Terminal app"
  echo "  (Terminal, iTerm, or the VS Code terminal - whichever you run autopilot from)."
else
  if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    echo "Note: you're on a Wayland session. Website automation works, but the real cursor,"
    echo "app switching and pause-on-touch need an Xorg session: log out, click the gear icon"
    echo "on the login screen and choose 'Ubuntu on Xorg' (or similar)."
  fi
  MISSING=""
  command -v wmctrl >/dev/null 2>&1 || MISSING="$MISSING wmctrl"
  if [ -n "$MISSING" ]; then
    echo "Optional, for switching to VS Code / other apps:  sudo apt install$MISSING"
  fi
fi

echo
echo "Done."
./autopilot doctor || true
echo
printf "Create your first automation now? [Y/n] "
read ans || ans="n"
case "$ans" in
  n|N) echo "Later, run:  ./autopilot      (it walks you through it)" ;;
  *) ./autopilot setup ;;
esac
