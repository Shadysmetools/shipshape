---
description: Control any app on this computer (not just the browser) from a goal in plain words - launch, type, read, check - recorded on video, with a visible banner, an app allow-list and N pass / M fail.
argument-hint: "<goal in plain words, e.g. open Notepad, type a line, check it, close without saving>"
---
Act as the `qa-desktop-tester` agent of this plugin for the goal: **$ARGUMENTS**

1. Read `qa.config.yaml`. It needs `desktop: {enabled: true, allow_apps: [...]}` with the app in the list. If not, stop and ask the owner to enable it (template: `${CLAUDE_PLUGIN_ROOT}/templates/qa.config.example.yaml`).
2. Check the engines: `python ${CLAUDE_PLUGIN_ROOT}/scripts/desktop.py engines`. Missing packages: `pip install --user pywinauto pyautogui mss pillow`.
3. Look at the app's controls (names and roles only): `python ${CLAUDE_PLUGIN_ROOT}/scripts/desktop.py inspect "<app>" --config qa.config.yaml`.
4. Turn the goal into a steps file `qa-runs/<date>-<goal>/desktop/steps.json`. Use the verbs in the docstring of `scripts/desktop.py` and the examples in `${CLAUDE_PLUGIN_ROOT}/templates/desktop-steps.notepad.json` and `desktop-steps.claude-desktop.json`. Every check gets a `case` id and a `say` line. Put `mask` steps before anything that shows private content (file dialogs, chat lists). Add a `cleanup` list that removes only what the run creates. Use test data only.
5. Dry run first and show the planned steps: `python ${CLAUDE_PLUGIN_ROOT}/scripts/desktop.py run <steps.json> --config qa.config.yaml --out qa-runs/<run>/desktop --dry-run`.
6. Real run (the owner approves it in the permission prompt): the same command without `--dry-run`, plus `--passes 2 --narrate`. Tell the owner first that a red "ShipShape is controlling this PC" banner will show, and that moving the mouse into a screen corner stops everything.
7. Report `N pass / M fail` from `qa-runs/<run>/desktop/QA-REPORT.md`, with the video paths (`pass-1/desktop.mp4`, `desktop-narrated.mp4`), the screenshots, the action log, and anything refused with its reason. Before a video leaves this computer, look at frames every 2 seconds and run `scripts/privacy.py scan`.

Never: send or submit in a chat app (no Enter), type a password, touch banking/payment/password apps or UAC/installer prompts, close another person's unsaved work, or touch the terminal running this session.
