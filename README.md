# Autopilot

> **Beta.** Built for Windows, macOS and Linux; see [Project status](#11-project-status).
> Please read [Responsible use](#10-responsible-use) before automating any site.

Automate a website and your desktop apps from the terminal, on Windows, macOS
and Linux. You answer a few questions once (site, login, pages, what to click
and type, which code editor and project to open, how fast and how long), and
Autopilot saves it as a **setup**. From then on you just run `autopilot`, and it
does it all, moving the real mouse cursor so you can watch:

- logs in to a site with **your own** account (asked at run time, never stored in files),
- visits the site's pages one by one, scrolling slowly and moving the cursor around,
- clicks buttons, types into boxes (for example a chat), presses keys, checks that text appears,
- switches to VS Code, Cursor or another app now and then, opens your project folder,
  sends keystrokes, scrolls, then goes back,
- pauses the moment you touch the mouse or keyboard and carries on 15 s after you stop,
- runs for as long as you say (`30m`, `2h`, `forever`), then prints a summary report.

---

## How it works

**What it is:** a command-line tool that walks through a website and your code
editor the way a person would, visibly, on your own screen. Typical uses are
demos and walkthroughs, manual-style smoke tests of an app you build (log in,
visit every page, try the chat, look for errors), and reproducing a user's path
through a product. You describe the walk-through once, then replay it any time.

**Built with:**

| Library | What it does in Autopilot |
|---|---|
| [Playwright for Python](https://playwright.dev/python/) | Controls the browser: opens pages, logs in, finds buttons, links and text boxes by their visible text, clicks, types, waits for pages to finish loading, reads console errors and takes screenshots of failures. It also connects to the Chrome you already have open (through Chrome's DevTools protocol) for `attach` mode. |
| [PyAutoGUI](https://pyautogui.readthedocs.io/) | Moves the **real** mouse pointer, presses keys and turns the scroll wheel. Playwright's own clicks are invisible and only work inside web pages; PyAutoGUI makes the movement visible and reaches desktop apps such as VS Code and Cursor. |
| PyGetWindow (Windows), AppleScript (macOS), wmctrl / xdotool (Linux) | Find app windows, bring them to the front and read their position, so the pointer stays inside the right window. |
| OS idle timers (Windows `GetLastInputInfo`, macOS `CGEventSource`, Linux XScreenSaver) | Tell when *you* used the mouse or keyboard, so the run can pause and later resume. |
| [keyring](https://github.com/jaraco/keyring) | Saves your login in the operating system's password store (Windows Credential Manager, macOS Keychain, Linux Secret Service) instead of in a file. |
| [PyYAML](https://pyyaml.org/) | Reads and writes setup files. |
| Python standard library | The command line (`argparse`), hidden password entry (`getpass`), launching apps (`subprocess`). |

**What happens during a run:**

```
autopilot setup ──► asks questions ──► ~/.autopilot/setups/<name>.yaml
                                       (login goes to the OS password store)

autopilot run ──► for each page, round after round, until the time is up:
   browser.py   Playwright logs in, finds the menu item
                PyAutoGUI glides the real pointer to it, Playwright clicks it
                runs the page's actions (click / type / press / check)
                scrolls and moves the pointer around for the time you chose
   apps.py      every N pages: bring VS Code / Cursor to the front,
                send your keystrokes with PyAutoGUI, scroll, go back
   human.py     the whole time: if you touch the mouse/keyboard, pause;
                after 15 s of quiet, bring the window back and continue
   report.py    a PASS/FAIL line per visit and a summary at the end
```

The pointer and the click work together: Playwright finds the element and its
position inside the page, Autopilot converts that to a screen position (window
position, browser toolbar, display scaling), PyAutoGUI glides the pointer there,
and then Playwright performs the click on the element itself. So the click
always hits the right element, even if the pointer lands a few pixels off.

---

## Contents

- [How it works](#how-it-works)
1. [Setup](#1-setup)
   - [Windows](#windows) · [macOS](#macos) · [Linux](#linux) · [Check your computer](#check-your-computer)
2. [Create your setup (once)](#2-create-your-setup-once)
3. [Running and stopping](#3-running-and-stopping)
4. [The settings file](#4-the-settings-file)
   - [General](#41-general) · [Website](#42-website) · [Logging in](#43-logging-in) ·
     [Pages](#44-pages) · [Steps (click, type, press ...)](#45-steps) · [Desktop apps](#46-desktop-apps) ·
     [Fine-tuning speed](#47-fine-tuning-speed)
5. [Examples](#5-examples)
6. [Using the browser you already have open](#6-using-the-browser-you-already-have-open)
7. [Reports](#7-reports)
8. [Troubleshooting](#8-troubleshooting)
9. [Sharing setups](#9-sharing-setups)
10. [Responsible use](#10-responsible-use)
11. [Project status](#11-project-status)
12. [Contributing](#12-contributing)

---

## 1. Setup

You need **Python 3.9+** and **Google Chrome** (Microsoft Edge or Chromium also work).
Setup creates a private Python environment inside this folder, so it doesn't
touch anything else on your computer.

### Windows

1. Install Python from <https://www.python.org/downloads/>. On the first installer
   screen, tick **"Add python.exe to PATH"**.
2. Install Google Chrome if you don't have it.
3. Get the code: `git clone https://github.com/darshanbajgain/autopilot` (or on
   GitHub click **Code → Download ZIP** and unzip it), e.g. into `C:\Users\you\autopilot`.
4. Double-click **`setup.bat`** (or run it in a terminal). Wait for "Done".
5. Open a terminal **in that folder**: in File Explorer, click the address bar,
   type `cmd` and press Enter.
6. Check it works:
   ```
   autopilot doctor
   ```

On Windows the command is `autopilot`. Run it from the Autopilot folder, or add
that folder to your PATH to use it anywhere.

### macOS

1. Install Python 3 from <https://www.python.org/downloads/> (or `brew install python`).
2. Install Google Chrome.
3. Get the code (`git clone https://github.com/darshanbajgain/autopilot`, or
   download the ZIP from GitHub and unzip it), then in Terminal:
   ```
   cd autopilot      # wherever you put it
   sh setup.sh
   ```
4. **Allow mouse and keyboard control** (needed for the cursor, typing and switching apps):
   *System Settings → Privacy & Security → Accessibility* → turn on the app you
   run Autopilot from (Terminal, iTerm, or VS Code). If it isn't listed, press `+` and add it.
   Restart that app afterwards.
5. Check it works:
   ```
   ./autopilot doctor
   ```

On macOS and Linux the command is `./autopilot` from the Autopilot folder.

### Linux

1. Install Python and venv, plus the window tool used for switching apps:
   ```
   sudo apt install python3 python3-venv wmctrl        # Debian / Ubuntu / Mint
   sudo dnf install python3 wmctrl                      # Fedora
   ```
2. Install Google Chrome (or let setup download Chromium for you).
3. Get the code (`git clone https://github.com/darshanbajgain/autopilot`, or the
   ZIP from GitHub), then:
   ```
   cd ~/autopilot
   sh setup.sh
   ./autopilot doctor
   ```
4. **Wayland vs Xorg.** Recent Ubuntu and Fedora use *Wayland* by default, which
   doesn't allow any program to move the mouse or switch windows. On Wayland,
   website automation still works fully, but the real cursor, app switching and
   pause-on-touch are switched off. To get them: log out, click the gear icon on
   the login screen, choose **"Ubuntu on Xorg"** (or "GNOME on Xorg" / "X11"), and
   log back in. `./autopilot doctor` tells you which one you're on.

### Check your computer

```
autopilot doctor
```

```
Autopilot 0.9.0 on Windows (11), Python 3.12.4

  ok Python 3.9 or newer
  ok Playwright installed
  ok Google Chrome found
  !! Your open Chrome allows 'attach' (remote debugging on)
       -> Only needed for 'attach: yes'. In Chrome open chrome://inspect/#remote-debugging and turn it on.
  ok Desktop control (cursor, apps, pause-on-touch)
  ok Can notice keyboard use (for pause-on-touch)
  ok Password store available (for 'saved' logins)
  ok 'code' command found
  -- 'cursor' command not on PATH (only needed for that editor)
```

`ok` means ready, `!!` comes with a tip, `--` is optional.

---

## 2. Create your setup (once)

At the end of `setup.bat` / `setup.sh` you're asked *"Create your first automation
now?"*. Say yes, or start it any time with:

```
autopilot setup
```

It walks you through four short sections. Press Enter to accept the value in
`[brackets]`.

**1/4 General**: how long each run lasts (`2h`, `forever` ...), speed
(slow / normal / fast), whether to move the real cursor, and whether to pause
when you touch the mouse or keyboard (and how long to wait before continuing:
15 s by default).

**2/4 Website**
- The site address, and whether to use a separate Chrome window or the Chrome you
  already have open ([section 6](#6-using-the-browser-you-already-have-open)).
- Your **email and password**, typed once and saved in your computer's password
  store (Windows Credential Manager / macOS Keychain / Linux keyring), never in
  the setup file. Runs then log in by themselves.
- Autopilot **opens the site and lists its menu pages**; you pick which to visit:
  ```
  Found 10 pages:
    1) Home
    2) Projects
    3) Reports
    ...
    7) Chat
  Which to visit? (Enter = all, or numbers like 1,2,5) [1,2,3,4,5,6,7,8,9,10]: 1,2,7
  ```
- Time on each page and the order.
- **Actions**: things to do on a page, step by step: click a button, type text
  (e.g. into a chat), press keys or shortcuts, wait, scroll, check that text appears.
  ```
  Steps to do on 'Chat', in order:
    1) click a button, link or tab
    2) type text (into a chat box, search, ...)
    3) press a key or shortcut
    4) wait
    5) scroll
    6) check that some text appears
    7) done
  ```

**3/4 Code editors and apps**: pick VS Code, Cursor, both, or another app. For
each editor: the **project folder** to open, and what to do there:
```
  1) Just look around and scroll (safe)
  2) Open files with Quick Open (Ctrl/Cmd+P)
  3) Type text into a scratch tab (never into your files)
  4) Run a command from the Command Palette
  5) My own keystrokes
```
"My own keystrokes" takes one per line:
```
      > mod+shift+e        (a shortcut; mod = Ctrl on Windows/Linux, Cmd on Mac)
      > wait 2s
      > type hello
      > Enter
      > scroll down
      >                    (empty line = done)
```
Then: switch to an app after every how many website pages, and for how long.

**4/4 Save**: the setup is saved and you're asked whether to run it now.

Change anything later with `autopilot edit` (same questions, your current
answers pre-filled), or make more setups with `autopilot setup` again.

Setups are saved in a folder in your home directory:
`C:\Users\<you>\.autopilot\setups\` on Windows, `~/.autopilot/setups/` on Mac/Linux.
They're plain text, so you can also edit them by hand ([section 4](#4-the-settings-file)).

---

## 3. Running and stopping

Just run:

```
autopilot
```

```
Autopilot 0.9.0

Setup: my-app  -  app.example.com, VS Code + Cursor, 2h, slow
    1) Run it
    2) Change its settings
    3) Test it (no clicking or typing)
    4) Create a new setup
    5) Use another setup (1 more)
    6) Quit
  Choose [1]:
```

Press Enter to run. Or skip the menu:

```
autopilot run                   # the last used setup
autopilot run my-app       # a setup by name
autopilot run recipes/web-chat.yaml   # or any settings file
```

```
Autopilot on Windows - run for 2h, speed slow.
  Website: https://app.example.com  (chrome)
  Pages: Home, Projects, Chat; 30s on each, in order.
  Apps: VS Code, Cursor - one after every 3 page(s)
  Touch the mouse or keyboard to pause; it resumes after 15s idle.
  Stop: press Ctrl+C in this terminal.
Starting in 5s - hands off the mouse (Ctrl+C to cancel)

--- Round 1 ---
  PASS  web Home                     31.2s
  PASS  web Projects              30.8s
  PASS  web Chat             38.0s  check 'Reply': ok
  PASS  app VS Code                  41.5s
  ...
```

- **Take over any time:** just use your computer. Moving the mouse or pressing a
  key pauses the run (`[paused]`). When you've left the mouse and keyboard alone
  for 15 seconds (your `resume_after`), it brings its window back and carries on
  (`[resumed]`). Paused time doesn't count against the time on a page.
- **Stop:** click the terminal window (that pauses it), then press **Ctrl+C**.
  It closes its browser tab and prints the summary. This is the only way to stop it.
- **When the time is up** (`run_for`), it stops by itself and prints the summary.

Test a setup without clicking or typing anything (logs in, opens each page,
looks for the buttons and boxes your actions use):

```
autopilot check
```

Change things for one run without editing the setup:

```
autopilot run --run-for 20m --speed fast
autopilot run --stay 1m             # 1 minute on each page
autopilot run --no-cursor           # don't move the real mouse
autopilot run --headless            # no browser window at all
```

Manage setups:

```
autopilot list              # all setups (* = the one 'autopilot run' uses)
autopilot edit [name]       # change one
autopilot delete name       # remove one
```

---

## 4. The settings file

`autopilot setup` writes this file for you; this section is for reading or
editing it by hand, or writing your own. Settings files use **YAML**: `name: value`, with **spaces** (never tabs) for
indentation. Put text in `"quotes"` if it contains `:` or `#`. Lists can be
written `[a, b, c]` or one item per line starting with `- `.

A file has up to three parts: general settings, `browser:` and `apps:`.
You need at least one of `browser:` and `apps:`.

### 4.1 General

| Setting | Default | What it does |
|---|---|---|
| `run_for` | `forever` | How long to run: `30s`, `20m`, `2h`, `1h30m`, or `forever`. |
| `speed` | `normal` | `slow`, `normal` or `fast`: cursor, scrolling and typing speed. |
| `real_cursor` | `yes` | Move the real mouse pointer so you can watch. `no` = work invisibly in the page. |
| `pause_when_touched` | `yes` | Pause when you use the mouse/keyboard. |
| `resume_after` | `15s` | How long you must be idle before it continues. |
| `tuning` | | Fine-grained speed, see [4.7](#47-fine-tuning-speed). |

### 4.2 Website

```yaml
browser:
  site: "https://app.example.com"
  attach: no
  channel: chrome
  login: ...
  pages: auto
  skip: ["Log out", "Delete"]
  stay_on_page: 30s
  order: in_order
  actions: ...
```

| Setting | Default | What it does |
|---|---|---|
| `site` | (required) | The site's address, starting with `https://`. |
| `attach` | `no` | `yes` = open a tab in the Chrome you already have open ([section 6](#6-using-the-browser-you-already-have-open)). `no` = start a separate browser window. |
| `channel` | `chrome` | `chrome`, `msedge`, or `chromium`. |
| `headless` | `no` | `yes` = no browser window (cursor is off). Good for quick tests. |
| `login` | none | See [4.3](#43-logging-in). |
| `pages` | `auto` | See [4.4](#44-pages). |
| `nav_area` | `auto` | Where the menu is, as a CSS selector (e.g. `"aside"`, `"#sidebar"`), if `auto` picks the wrong one. |
| `skip` | log out, sign out, delete | Menu items never to click. |
| `stay_on_page` | `30s` | Time on each page: scrolling down and up and moving the cursor around. |
| `order` | `in_order` | `in_order` or `random` (shuffled every round). |
| `actions` | none | Things to do on particular pages, see [4.5](#45-steps). |

### 4.3 Logging in

Credentials are **never** written in the settings file. Choose how they're given:

```yaml
  login:
    credentials: ask          # ask | saved | env
    logged_in_when: "Dashboard"
```

| `credentials:` | How it works |
|---|---|
| `saved` (what `autopilot setup` uses) | Taken from your computer's password store (Windows Credential Manager, macOS Keychain, Linux keyring), entered once during setup. If it's missing, it's asked and saved at the start of a run. Remove it with `autopilot forget app.example.com`. |
| `ask` | The terminal asks for your email and password at the start of every run. The password is hidden while typing and is forgotten afterwards. |
| `env` | Read from a `<setup-name>.env` or `.env` file next to the settings file. Setup uses this when the computer has no password store. Copy `.env.example` and fill it in. **Keep it private.** |

With `attach: yes` and if you're already signed in in that browser, the login is
skipped and nothing is asked.

Other login settings, only needed if the automatic detection doesn't work:

| Setting | Example | What it does |
|---|---|---|
| `url` | `"/login"` | The sign-in page, if it isn't the site's front page. |
| `logged_in_when` | `"Projects"` | Text that only appears once signed in. Recommended: it makes login detection reliable. |
| `email_field` | `"Email address"` | The email box's placeholder, label or a CSS selector. |
| `password_field` | `"#password"` | Same for the password box. |
| `submit_button` | `"Sign in"` | The button's text. |
| `email_env`, `password_env` | `MY_EMAIL` | Names of the variables in `.env` (default `AUTOPILOT_EMAIL` / `AUTOPILOT_PASSWORD`). |

Two-step logins (email first, then a password page) are handled automatically.
Captchas and 2-factor codes can't be automated: sign in yourself in your own
Chrome and use `attach: yes`.

### 4.4 Pages

```yaml
  pages: auto
```
finds the site's sidebar or top menu by itself and visits every link in it
(except those in `skip`). Run `autopilot check` to see what it found.

Or list them by the text on the menu items:

```yaml
  pages: [Home, Projects, "Reports & stats", Settings]
```

- Matching ignores upper/lower case, and the start of a name is enough:
  `"Reports & st"` matches "Reports & stats".
- An entry starting with `/` or `https://` is opened as an address instead of clicked:
  `pages: [Home, /billing, "https://app.example.com/help"]`

### 4.5 Steps

Steps say what to do. On a website they go under `actions:`, per page:

```yaml
  actions:
    - page: "Chat"     # the page name (or "*" for every page)
      every: 1                 # 2 = only every second visit to that page
      steps:
        - click: "New chat"
        - type: "Summarize this page in one sentence"
          into: "Ask anything"
        - press: Enter
        - wait: 20s
        - expect: "Summary"
```

Steps run when the page opens; then the normal browsing (scroll and cursor) fills
the rest of `stay_on_page`.

| Step | Website | App | Example | What it does |
|---|:-:|:-:|---|---|
| `click` | ✓ | | `click: "Save"` | Glides to and clicks a button/link/tab by its text. |
| `type` | ✓ | ✓ | `type: "hello"` | Types text at human speed. On a website add `into:` with the box's placeholder or label (otherwise the first text box). `\n` in double quotes is Enter. |
| `press` | ✓ | ✓ | `press: mod+s` | Presses a key or shortcut. |
| `wait` | ✓ | ✓ | `wait: 10s` | Waits (still pauses if you touch the mouse). |
| `scroll` | ✓ | ✓ | `scroll: down` | `down`, `up`, `top` or `bottom`. |
| `wander` | ✓ | ✓ | `wander: 15s` | Just moves the cursor around for a while. |
| `goto` | ✓ | | `goto: "/settings/profile"` | Opens an address on the site. |
| `expect` | ✓ | | `expect: "Saved"` | Checks the text appears (waits up to 30 s, or `timeout:`). A missing text marks the visit **FAIL** in the report. |

Any step can have `timeout:`, e.g. `timeout: 60s` for a slow reply.

**Finding things.** `click`, `into` and `expect` look for visible text first:
buttons, links, tabs, labels, placeholders. If text isn't enough, use a CSS
selector (starting with `#`, `.` or `[`), e.g. `click: "#send-button"` or
`into: "[data-testid=chat-input]"`.

**Keys** for `press`: `Enter`, `Escape`, `Tab`, `Space`, `Backspace`, `Delete`,
`Up`, `Down`, `Left`, `Right`, `Home`, `End`, `PageUp`, `PageDown`, `F1`–`F12`,
letters and digits, combined with `+`: `ctrl+shift+p`, `alt+tab`.
**`mod`** means Ctrl on Windows/Linux and Cmd on Mac, so `mod+s` saves everywhere.
Use `mod` in settings you share.

### 4.6 Desktop apps

```yaml
apps:
  every: 3            # visit an app after every 3 website pages
  stay: 40s           # time in each app
  list:
    - app: vscode
      folder: "~/projects/my-repo"
    - app: cursor
      folder: "C:/Users/you/projects/other-repo"
      stay: 1m        # overrides 'stay' for this app
      steps:
        - press: mod+p
        - type: "app.py"
        - press: Enter
```

Apps take turns: the first time it goes to the first app, next time the second,
and so on. Without a `browser:` section, it just cycles through the apps.

In each app it: brings the window to the front (opening the app on `folder` if
needed), runs the `steps`, then for the rest of `stay` moves the cursor around
the window and scrolls with the mouse wheel. It never clicks inside the app.

| Setting | What it does |
|---|---|
| `app` | `vscode`, `cursor`, or `custom`. |
| `folder` | Project folder to open (`~` = your home folder). |
| `steps` | Keystrokes etc. (`type`, `press`, `wait`, `scroll`, `wander`). |
| `typing_target` | Where typed text goes, see below. |
| `stay` | Time in this app (overrides `apps: stay`). |
| `command`, `window_title`, `mac_app` | For `custom` apps, see below. |

**Typing into editors is safe by default.** With `typing_target: scratch` (the
default for VS Code and Cursor), Autopilot first opens a scratch file,
`~/.autopilot/scratch.txt`, types there, then empties and saves it. Your project
files are never typed into. Set `typing_target: focused` to send keys to
whatever has focus in the app instead. Use it for shortcuts like Quick Open
(`mod+p`) or the command palette, and be careful: with `focused`, typed text
can end up in an open file.

**Other apps** (`app: custom`):

```yaml
    - app: custom
      name: Notes
      command: "notepad"             # how to start it (Windows)
      window_title: "Notepad"        # text in its window title
    - app: custom
      command: "gedit"               # Linux
      window_title: "gedit"
    - app: custom
      mac_app: "Notes"               # macOS: the app's name in /Applications
```

**VS Code / Cursor not found?** Open the editor, press `Ctrl+Shift+P`
(`Cmd+Shift+P` on Mac), run **"Shell Command: Install 'code' command in PATH"**
(or `cursor`), then restart your terminal.

### 4.7 Fine-tuning speed

`speed:` sets all of these at once. Override any under `tuning:`:

```yaml
speed: slow
tuning:
  cursor_move: 2.5     # seconds per cursor glide
  scroll_step: 120     # pixels per scroll step (smaller = slower)
  gap_min: 1.5         # pause between moves: random between gap_min ...
  gap_max: 3.0         # ... and gap_max seconds
  typing_delay: 180    # milliseconds between typed characters
```

| | `slow` | `normal` | `fast` |
|---|---|---|---|
| `cursor_move` | 1.8 | 1.2 | 0.6 |
| `scroll_step` | 150 | 250 | 450 |
| `gap_min` / `gap_max` | 1.2 / 2.5 | 0.6 / 1.5 | 0.3 / 0.8 |
| `typing_delay` | 140 | 80 | 35 |

---

## 5. Examples

Ready-made files are in the `recipes/` folder. Copy one, change the site and
names, and run it.

### Walk through a site's menu for an hour

```yaml
run_for: 1h
speed: slow
browser:
  site: "https://example.com"
  pages: auto
  stay_on_page: 30s
```

### A web app with a login, chosen pages, random order, forever

```yaml
run_for: forever
browser:
  site: "https://app.example.com"
  login:
    credentials: ask
    logged_in_when: "Dashboard"
  pages: [Dashboard, Projects, Reports, Settings]
  order: random
  stay_on_page: 45s
```

### Type into a web chat and check for a reply

```yaml
run_for: 30m
browser:
  site: "https://app.example.com"
  login:
    credentials: saved
  pages: auto
  actions:
    - page: "Chat"
      every: 2
      steps:
        - click: "New chat"
        - type: "Give me three ideas for a team lunch"
          into: "Ask anything"
        - press: Enter
        - expect: "1."
          timeout: 60s
```

### Browser plus VS Code on your project

```yaml
run_for: 2h
speed: slow
browser:
  site: "https://app.example.com"
  attach: yes
  pages: auto
  stay_on_page: 40s
apps:
  every: 3
  stay: 60s
  list:
    - app: vscode
      folder: "~/projects/my-repo"
      typing_target: focused
      steps:
        - press: mod+p        # Quick Open
        - type: "README"
        - press: Enter
        - wait: 3s
        - scroll: down
```

### Only editors, no website

```yaml
run_for: 1h
apps:
  stay: 45s
  list:
    - app: cursor
      folder: "~/projects/my-repo"
      steps:
        - type: "TODO: review the login flow\n"    # into the scratch file
    - app: vscode
      folder: "~/projects/other-repo"
```

### Every action on one page

```yaml
browser:
  site: "https://app.example.com"
  pages: [Home, Settings]
  actions:
    - page: "Settings"
      steps:
        - scroll: bottom
        - wait: 2s
        - scroll: top
        - click: "Notifications"           # a tab on the settings page
        - expect: "Email notifications"
        - goto: "/settings/profile"
        - type: "Hello from Autopilot"
          into: "Bio"
        - press: mod+a                     # select it all ...
        - press: Backspace                 # ... and remove it again (nothing saved)
        - wander: 10s
```

---

## 6. Using the browser you already have open

With `attach: yes` (or `--attach`), Autopilot opens a new tab in the Chrome
you're already using, with your sign-ins, instead of a separate window.

One-time setup (Chrome 144 or newer; check at `chrome://settings/help`):

1. In Chrome, open **`chrome://inspect/#remote-debugging`** and turn remote debugging **on**.
2. Run `autopilot` (with "The Chrome you already have open" chosen in setup, or `attach: yes`).
3. Chrome shows a dialog asking to allow the connection. Click **Allow**
   (it asks every time; that's a Chrome safety measure).

Autopilot only closes its own tab at the end; the rest of your Chrome is left alone.

Older Chrome, or Edge/Chromium: close the browser completely and start it with a
debugging port, then run with `attach: yes`:

```
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\chrome-autopilot
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-autopilot
# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-autopilot
```

---

## 7. Reports

Every visit prints one line: `PASS`/`FAIL`, how long it took, console errors
seen on the page, and `expect` results. At the end you get a summary:

```
========================================================================
Run finished: time's up (2h)
Ran for 2h; 214 visits, 211 passed, 3 failed.

  Where                        Visits  Failed  Avg time  Console err
  web Home                         22       0     31.2s            0
  web Chat                 21       2     38.9s            4
! web Calendar                     21       1     30.5s            0
  app VS Code                      18       0     40.2s            0

Problems seen:
  - web Chat: check 'Summary' not found
  - web Calendar: menu item 'Calendar' not found
========================================================================
Saved to reports/run-20261015-143012.txt
```

The summary is saved in the `reports` folder (`~/.autopilot/reports/`, or next to
the settings file for files outside it). When a page fails, a screenshot is saved
in the `screenshots` folder beside it.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `'autopilot' is not recognized` (Windows) | Run it from the Autopilot folder, or run `setup.bat` first. |
| `Autopilot isn't set up yet` | Run `setup.bat` (Windows) or `sh setup.sh` (Mac/Linux). |
| `Problem in the settings file: ...` | The message names the setting and the fix. Common causes: tabs instead of spaces, a missing `"` around text with `:`. |
| `LOGIN FAILED` | Look at `~/.autopilot/screenshots/login_failed.png`. Wrong password? Run `autopilot edit` and enter it again. Add `logged_in_when:`, set `login: url:`, or `email_field:` / `submit_button:`. With captchas/2FA, sign in yourself and use `attach: yes`. |
| `menu item 'X' not found` | Run `autopilot edit` and let it list the pages again, or `autopilot check` to see which names it can see. If it found the wrong menu, set `nav_area:`. |
| The cursor lands next to things | Set the browser zoom to 100% (`Ctrl+0` / `Cmd+0`), close or undock DevTools. Cursor position doesn't affect the clicks themselves. |
| Chrome isn't found | Install Chrome, or set `channel: msedge`, or `channel: chromium` and run `.venv/bin/python -m playwright install chromium` (Windows: `.venv\Scripts\python -m playwright install chromium`). |
| `attach` can't connect | Turn on `chrome://inspect/#remote-debugging`, click **Allow** in Chrome's dialog, or start Chrome with a port (section 6). |
| Nothing moves on Linux | You're on Wayland (see Linux setup), or install `wmctrl` for app switching. |
| Nothing moves on macOS | Allow your Terminal in *Privacy & Security → Accessibility*, then restart the Terminal. |
| VS Code / Cursor won't open | Install the `code` / `cursor` command (section 4.6), or open the editor yourself once. |
| `Error: ... Full details saved to ...last-error.txt` | Something unexpected broke. Send that file to whoever maintains your copy. |
| It pauses all the time | Something is moving the mouse (e.g. a touchpad). Increase `resume_after`, or `pause_when_touched: no`. |
| It doesn't pause when I type (Linux) | `sudo apt install libxss1` (or `xprintidle`). |

Run `autopilot doctor` any time to check the setup.

---

## 9. Sharing setups

- Each person installs Autopilot once on their own computer (section 1).
- Setups never contain passwords, so they're safe to share: send someone your
  file from `~/.autopilot/setups/`, they put it in theirs and run
  `autopilot edit <name>` to enter their own login and project folders.
- Put setups you want everyone to have in `recipes/` and run them with
  `autopilot run recipes/<file>.yaml`.
- Write shortcuts with `mod` (not `ctrl` or `cmd`) so they work on every OS.

---

## 10. Responsible use

Autopilot drives a real browser and a real mouse and keyboard. That's useful for
demos, manual-style smoke tests of your own app, and walking through a product
hands-free, and it can also be misused. By using it you agree to:

- **Only automate sites, apps and accounts you own or have permission to automate.**
  Many sites' terms of service forbid automated access. Check before you point
  Autopilot at someone else's service.
- **Not use it to deceive anyone.** Don't use it to fake activity or presence
  (for example to fool time-tracking or employee-monitoring software), to inflate
  views, likes, followers or other engagement, to create accounts, or to send
  spam or bulk messages.
- **Not use it to get around protections.** Autopilot doesn't solve captchas or
  2-factor prompts and isn't meant to evade bot detection or rate limits.
- **Be gentle with servers.** Keep `stay_on_page` reasonable; don't run many
  copies against a site you don't control.
- **Remember actions are real.** Chat messages, form submissions and clicks
  happen for real and may cost credits, send emails or change data.

You're responsible for how you use it. The software is provided "as is", without
warranty of any kind (see [LICENSE](LICENSE)).

---

## 11. Project status

Autopilot is **beta**. What's been tested and what hasn't:

| Area | Status |
|---|---|
| Website automation (login, page discovery, actions, reports) | Tested on Windows and Linux |
| Real cursor, pause when you take over, resume | Tested on Windows and Linux (X11) |
| Setup wizard, saved setups, menu | Tested on Windows and Linux |
| Switching to VS Code / Cursor and keystrokes | Needs more testing, especially on macOS |
| macOS in general | Not yet tested on a real Mac: reports welcome |
| Linux Wayland | Website automation only (by design, see Linux setup) |

Found a problem? Open an issue with the terminal output, your OS, and (if there
was one) the file `~/.autopilot/last-error.txt`. **Remove any passwords, emails
or private URLs before posting.**

---

## 12. Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how the
code is organised and how to test changes.

---

## License

[MIT](LICENSE). Autopilot builds on these open-source libraries, each under its
own license: [Playwright](https://github.com/microsoft/playwright-python) (Apache-2.0),
[PyAutoGUI](https://github.com/asweigart/pyautogui) (BSD-3-Clause),
[PyYAML](https://github.com/yaml/pyyaml) (MIT) and
[keyring](https://github.com/jaraco/keyring) (MIT).

---

### Command reference

```
autopilot                           menu: run / change / test / new / switch setup
autopilot setup [name]              create a setup by answering questions
autopilot edit [name]               change a setup (default: the last used)
autopilot list                      list setups
autopilot delete name               delete a setup
autopilot check [name|file] [--show]  test it without clicking or typing
autopilot run [name|file] [options] run it (default: the last used setup)
    --run-for 30m|2h|forever  --speed slow|normal|fast  --stay 45s
    --attach  --headless  --no-cursor  --no-pause
autopilot doctor                    check this computer
autopilot forget site.com           remove a saved login
autopilot --version
```
