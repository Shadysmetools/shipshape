---
name: desktop-control
description: Control the whole desktop (any app, native dialogs, file pickers, Electron apps, OS settings) on Windows or macOS for QA, with recording and safety gates. Use for "test the desktop app", "click through the installer dialog", "check the file picker", or any flow a browser tool cannot reach. Requires desktop.enabled in qa.config.yaml.
---
# Desktop control
1. Prefer Claude's computer-use capability when it is available. Otherwise use the kit's layer below.
2. Enable per project: `desktop: {enabled: true, allow_apps: ["notepad", "TextEdit"]}` in `qa.config.yaml`.
3. Steps JSON: `open | focus | type | key | click | wait | screenshot` (see the docstring of `scripts/desktop.py`).
4. Dry run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/desktop.py run steps.json --config qa.config.yaml --dry-run`
5. Real run (recorded with ffmpeg gdigrab/avfoundation): drop `--dry-run`. Narrate afterwards with `narrator.py mix`.

Safety: allow-listed apps only; never password fields; never banking/payment/password apps; irreversible steps need the user's OK and `"confirmed": true`; a red on-screen notice while it runs; mouse to a corner = emergency stop; every action logged to `desktop-actions.jsonl`.
Install: `pip install pyautogui pywinauto` (Windows) or `pip install pyautogui` (macOS), or run the kit's installer with `--with-desktop`.
