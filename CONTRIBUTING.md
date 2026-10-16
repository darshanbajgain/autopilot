# Contributing to Autopilot

Thanks for helping! Bug reports, testing on macOS/Linux, and small focused pull
requests are all welcome.

## Reporting a problem

Open an issue with:

- your OS and version (`autopilot doctor` prints it),
- what you ran and the terminal output,
- `~/.autopilot/last-error.txt` if the error mentions it.

**Remove passwords, emails, private URLs and anything else private first.**
Never attach your `.env` files or setup files that point at private sites.

## How the code is organised

All code is in `src/autopilot/`:

| File | What it does |
|---|---|
| `cli.py` | Commands (`autopilot`, `setup`, `run`, `check`, `doctor` ...) and the menu |
| `wizard.py` | The setup / edit questions |
| `store.py` | Where setups are saved (`~/.autopilot/setups`) |
| `config.py` | Reading and checking settings files, defaults, speed presets |
| `creds.py` | Logins: OS password store, `.env` files, asking in the terminal |
| `runner.py` | The run loop, timing, countdown |
| `browser.py` | Website automation with Playwright |
| `apps.py` | Visiting VS Code / Cursor / other apps |
| `desktop.py` | Mouse, keyboard and window switching per OS |
| `human.py` | Noticing when you take over, pausing and resuming |
| `report.py` | Per-visit lines and the end-of-run summary |

## Developing

```
git clone https://github.com/darshanbajgain/autopilot
cd autopilot
sh setup.sh            # or setup.bat on Windows
./autopilot doctor
```

To keep your test setups away from your real ones, point Autopilot at another
folder while developing:

```
AUTOPILOT_HOME=/tmp/ap-dev ./autopilot setup        # macOS / Linux
set AUTOPILOT_HOME=C:\temp\ap-dev && autopilot setup  # Windows
```

Before opening a pull request:

- test against a site you control (a local page is easiest) - never someone
  else's site,
- run `autopilot check` and a short `autopilot run --run-for 1m` on your OS,
- say in the PR which OSes you tested on.

## Ground rules

- Keep it safe by default: nothing that types into project files, saves files,
  or submits forms unless the user explicitly set it up.
- No features for evading bot detection, solving captchas, faking activity or
  inflating engagement (see "Responsible use" in the README).
- Keep error messages plain and actionable; the tool is used by non-developers.
