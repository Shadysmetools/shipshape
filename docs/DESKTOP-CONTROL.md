# Desktop control: drive any app on this computer

ShipShape can control any app on the computer, not only the browser. It can open Notepad, Claude Desktop, an Electron app or an OS dialog, then type, click, read what is on screen and check the result. It records a video while it works.

## The easy way

```
/qa-desktop "open Notepad, type a test line, check it is there, close it without saving"
```

The `qa-desktop-tester` agent:
1. Looks at the app's controls (names and roles).
2. Writes the steps.
3. Shows you a dry run.
4. Runs it twice on video once you approve the permission prompt.
5. Answers with **N pass / M fail**, the video paths, the screenshots and the action log.

## Turn it on (once per project)

In `qa.config.yaml`:

```yaml
desktop:
  enabled: true
  allow_apps: [notepad, claude]   # process names; "title:Calculator" matches a window title instead
  step_timeout: 20                # seconds per step
  run_timeout: 180                # seconds per run (also the recording's hard limit)
```

Install the extras once:
- `pip install --user pywinauto pyautogui mss pillow`, or `bin/install.ps1 -WithDesktop` / `bin/install.sh --with-desktop`.
- macOS also needs Accessibility and Screen Recording for the terminal (System Settings > Privacy & Security).
- Check with `python scripts/desktop.py engines`.

## Engines

| Engine | What it is | When |
|---|---|---|
| `uia` (default, Windows) | Windows UI Automation through pywinauto: finds controls by name and role, clicks, types, reads text | Every normal app: Notepad, Office, Electron apps such as Claude Desktop, OS dialogs |
| `pixel` (fallback) | Screenshot plus coordinate click and typing through pyautogui | Apps with no controls (canvas, games): `{"do": "click", "at": [0.5, 0.9]}` |
| Claude computer use (optional) | Anthropic API tool `{"type": "computer_toolset_20260801"}` on `claude-opus-5-5`, no beta header | Open-ended exploration of an unknown app. It needs **your own** `ANTHROPIC_API_KEY`: `python scripts/keys.py set ANTHROPIC_API_KEY`. ShipShape ships no keys and never bundles one. |
| macOS | osascript plus pyautogui | Same steps, fewer control-level checks |

A computer-use MCP inside your Claude session also works. The plain-language hook in `hooks/hooks.json` checks each of its actions.

## Steps file

A steps file is a JSON list, or `{"name": ..., "steps": [...], "cleanup": [...]}`. Examples:
- `templates/desktop-steps.notepad.json`: type, read back, Save As then Cancel, close the tab with Don't save.
- `templates/desktop-steps.claude-desktop.json`: type into the chat box, check it, clear it, never send.

| Step | Example |
|---|---|
| launch | `{"do": "launch", "app": "Notepad", "require_new": true}`: by path, Start-menu name or PATH; waits for the window |
| focus / minimize / close | `{"do": "close", "only_if_launched": true, "otherwise": "minimize"}` |
| type / key / click / scroll | `{"do": "type", "control": {"role": "Edit", "name": "Write your prompt to Claude"}, "text": "..."}` |
| read / clipboard | `{"do": "read", "control": {...}, "save_as": "typed"}` |
| checks | `assert_text` (`equals`, `contains`, `equals_var`), `assert_control` (`present`), `assert_window`, `wait_text`, `wait_window` |
| privacy | `mask` (`rect`, `control` (+ `largest`, `optional`), `above_control`, `outside_control`, `within`, `regions` + `replace`, `allow_large`), `unmask` |
| evidence | `record_start`, `screenshot` (`region`: `window`, `screen` or `monitor:N`; every monitor is supported) |

Every step can carry:
- `case`: the report id;
- `say`: the narration line;
- `shot: false`: no screenshot;
- `timeout`;
- `stop_on_fail`;
- `confirmed: true`: only after the owner's OK.

Look before writing:
- `python scripts/desktop.py windows` lists only allow-listed windows.
- `python scripts/desktop.py inspect "Notepad"` lists control names and roles.

Run:

```
python scripts/desktop.py run steps.json --config qa.config.yaml --out qa-runs/<run>/desktop --dry-run
python scripts/desktop.py run steps.json --config qa.config.yaml --out qa-runs/<run>/desktop --passes 2 --narrate
```

## Evidence

Everything lands in `<out>/` (or `<out>/pass-1`, `pass-2`):
- `desktop.mp4`: ffmpeg gdigrab of **the target window only**, with a hard length limit;
- `desktop-narrated.mp4` and `.srt`: the free edge voice reads each step's `say`. One narrator at a time: a step with a `say` waits until the previous line has been spoken, and the mix never lets two lines overlap (the last frame is held if the last line runs past the end). The file has exactly one audio track;
- one masked screenshot per step;
- `desktop-actions.jsonl`: every action, refusal and timing; text lengths only, never the text;
- `results.json` and `QA-REPORT.md`: N pass / M fail. Two passes that disagree are FLAKY.

## Safety: what it will never do

| Gate | How |
|---|---|
| Allow-list | Only apps in `desktop.allow_apps`, checked on the step (before the run, also by `hooks/hook_guard.py`) and on the real focused window |
| Right window only | Before typing or a shortcut, the window under test must be in front **and** the UIA element holding the keyboard focus must belong to its process. Otherwise nothing is sent (a terminal tab never gets a key). Before every key, click and **every typed character**, the focused window must be the window under test or its own dialog. If anything jumps in front, typing stops at once (at most one character can land there). Overlays hand the focus back to the window under test, never to whatever was in front. |
| Never a terminal | Terminals, editors and the agent's own process chain are refused |
| Person at the keyboard | If someone is typing or moving the mouse, the run waits for a quiet moment, then stops |
| Visible banner | A red "ShipShape is controlling this PC" banner while it runs; it is in the video too |
| Emergency stop | Move the mouse into a screen corner (pyautogui FAILSAFE): the run aborts and nothing else runs |
| No passwords, payments, installers | Password fields are refused (UIA IsPassword) and blacked out in screenshots. Banking, payment, wallet and password-manager apps are refused, and so are UAC and installer prompts. |
| Irreversible needs the owner | delete, send, submit, purchase, pay, install, uninstall, format, discard, "Don't save", and Enter or a newline in a chat app all stop and ask. A step runs only with `"confirmed": true` after the owner's OK in the conversation. |
| Nobody's work is lost | `close` sends WM_CLOSE (never a process kill). If the app asks to save, it presses **Cancel**. `only_if_launched` closes only windows the run opened. `cleanup` steps remove only the run's own test data. |
| Timeouts | Per step (`step_timeout`) and per run (`run_timeout`, plus a watchdog that hard-stops the process) |
| Privacy | Only the target window is recorded. `mask` overlays **blur** (pixelate) only the private parts, such as the chat list, account name, recent items, file dialogs and tab names, in the video and the screenshots. The app and what the test does stay visible. By default the masks may cover at most 40% of the window (`desktop.mask_max_cover`), and a mask never covers the control the next steps type into or read: it is cut out. A deliberate full cover (a Save As dialog lists folders) needs `"allow_large": true`. Masks are confirmed on screen before the run continues. The mouse is parked so file-list tooltips do not pop up. Recording stops before a window closes or minimises, so what is behind it is never filmed. |
| Clipboard | Restored to what you had after the run |

What it cannot guarantee: a window that steals the focus in the instant between the focus check and a key press can receive that one key. This is why steps never include Enter in a chat app or a password, and why typing stops the moment the focus moves.

Before a video leaves the computer, look at frames every ~2 seconds and run `python scripts/privacy.py scan` on any text. A mask covers what you asked it to cover, nothing more. For Claude Desktop the template blurs the sidebar (`{"role": "Group", "name": "Sidebar", "largest": true}`: chats and account) and the recent-items list.
