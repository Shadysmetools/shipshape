---
name: desktop-control
description: Control the whole computer, not just the browser. Launch and drive any local app (Notepad, Claude Desktop, Electron apps, OS dialogs, file pickers) on Windows or macOS for QA, recorded and gated. Use for "test the desktop app", "type into Claude Desktop", "check the file picker", "control this PC", or any flow a browser tool cannot reach. Requires desktop.enabled in qa.config.yaml.
---
# Desktop control (full device)
1. Enable it per project: `desktop: {enabled: true, allow_apps: ["notepad", "claude"], step_timeout: 20, run_timeout: 180}` in `qa.config.yaml`. Entries match the app's process name; `title:` entries match a window title.
2. Easiest way in: `/qa-desktop "<goal in plain words>"`. The qa-desktop-tester agent writes the steps, dry-runs them, runs them and reports N pass / M fail.
3. Engines: Windows UI Automation (pywinauto `uia`), then pyautogui pixels, plus optional Claude computer use with your own `ANTHROPIC_API_KEY`. Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/desktop.py engines` to see which are available.
4. Steps: `launch | focus | minimize | close | wait_window | wait_text | click | type | key | scroll | read | clipboard_set | clipboard_get | assert_text | assert_control | assert_window | mask | unmask | record_start | screenshot | wait`. They are listed in the docstring of `scripts/desktop.py`; the examples are in `templates/desktop-steps.*.json`.
5. Look before you write: `desktop.py windows` and `desktop.py inspect "<app>"`.
6. Dry run: `desktop.py run steps.json --config qa.config.yaml --dry-run`. Real run: drop `--dry-run` and add `--passes 2 --narrate`.

Safety:
- Allow-listed apps only. Focus is checked before every input, and before every typed character.
- Never a terminal. If a person is typing, the run waits.
- No passwords, banking/payment apps or UAC prompts.
- Irreversible steps and Enter in chat apps need the user's OK and `"confirmed": true`.
- A red "ShipShape is controlling this PC" banner shows while a run is active. Moving the mouse into a screen corner is the emergency stop.
- Privacy masks show in both the video and the screenshots. Only the target window is recorded.
- Every action goes to `desktop-actions.jsonl` (text lengths only).

Install:
- `pip install --user pywinauto pyautogui mss pillow`, or the installer's `--with-desktop` / `-WithDesktop`.
- macOS: grant Accessibility and Screen Recording.

Full guide: `docs/DESKTOP-CONTROL.md`.
