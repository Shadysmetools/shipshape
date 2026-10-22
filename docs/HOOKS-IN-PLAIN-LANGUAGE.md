# Hooks in plain language

A hook is a rule Claude Code checks automatically at a moment in the session (before a tool runs, when Claude wants to stop, when a session starts). Most of ShipShape's hooks are written in **plain English**: a small model reads the situation and the rule, and answers "ok" or "not ok, because...". No shell scripting needed.

Reference (Claude Code docs): hooks and prompt/agent hook types: https://code.claude.com/docs/en/hooks.md · plugin hook files: https://code.claude.com/docs/en/plugins/components.md

## The three hook types ShipShape uses
| Type | What judges | Can read files? | Use it for |
|---|---|---|---|
| `prompt` | a fast model, one look at the hook input | no | rules about the action itself (a push command, a final message) |
| `agent` | a small subagent with Read/Grep/Glob (up to ~50 turns) | yes | rules that need context: "did the user approve this in the conversation?", "is this channel in the config?" |
| `command` | a script | yes | checks a model cannot do reliably (scanning the staged diff for secrets) |

`prompt` and `agent` hooks receive the hook input JSON where you write `$ARGUMENTS` (tool name, tool input, `transcript_path`, `cwd`, and for Stop the `last_assistant_message`). They must answer `{"ok": true}` or `{"ok": false, "reason": "..."}`. On **PreToolUse**, `ok: false` blocks the tool call; with `"continueOnBlock": true` the reason goes back to Claude so it can adjust instead of ending the turn. On **Stop**, `ok: false` sends the reason back and Claude keeps working.

## How to build one, step by step
1. **Pick the moment**: `PreToolUse` (before an action), `Stop` (before Claude finishes), `UserPromptSubmit`, `PostToolUse`, ... (`SessionStart` only supports `command`).
2. **Narrow it**: `matcher` is a regex on the tool name (`Bash`, `mcp__.*odoo.*__write.*`). For Bash, add `"if": "Bash(git push*)"` (permission-rule syntax, one rule per hook) so the model is only called for matching commands. Narrow matchers keep the session fast.
3. **Write the rule like you would tell a colleague**: what to look at, when it is fine, when it is not, and the exact reason to give. Always include `$ARGUMENTS`, and the answer format.
4. **Choose `prompt` or `agent`**: if the rule needs the conversation or a file, use `agent` and tell it to read `transcript_path` (user messages only) or the config file.
5. **Avoid loops**: a Stop hook must say "if `stop_hook_active` is true, answer ok".
6. **Test it**: run `claude --debug` and trigger the action; or `claude plugin validate .` for the JSON.

## ShipShape's hooks (in `hooks/hooks.json`)
| When | Type | The rule, in words |
|---|---|---|
| Session start | command | Print "ShipShape ready" and the commands. No network. |
| Claude wants to stop | prompt | If the last message reports test results, it must say "N pass / M fail" with evidence paths, and never just "all green". |
| Before an Odoo write tool | agent | Allow only if the user approved this specific write in this conversation; a relayed approval does not count. |
| Before an upload/share/send/post tool | agent | Block names, emails, phones, keys, client data, and sends the user did not ask for; security findings only as a count. |
| Before `git commit` | command | Scan the staged diff for secrets and personal data (a model cannot see the staged diff). |
| Before `git push` | prompt | Block force-pushes and pushes to main/master/production. |
| Before `notify.py --send` | agent | Only channels listed and enabled in qa.config.yaml, and only after the user said send. |
| Before `desktop.py run` | agent | Desktop enabled, apps on the allow-list, no banking/payment/password apps or fields, irreversible steps approved. |
| Before computer-use actions | prompt | No password fields, no banking/payment apps, no irreversible action without approval. |

### Example: the Stop rule
```json
{"type": "prompt", "timeout": 30,
 "prompt": "You check how Claude reports test or QA results. Hook input: $ARGUMENTS\nIf stop_hook_active is true, answer {\"ok\": true}. ... If the rule is broken, answer {\"ok\": false, \"reason\": \"Report the results as N pass / M fail with the evidence paths, and say what was not checked.\"}. Otherwise answer {\"ok\": true}."}
```

### Example: block pushes to production
```json
{"matcher": "Bash", "hooks": [{"type": "prompt", "if": "Bash(git push*)", "continueOnBlock": true,
  "prompt": "Guard for git push. Hook input: $ARGUMENTS\nBlock it ({\"ok\": false, \"reason\": \"...\"}) if it force-pushes or pushes to main, master or production. Otherwise answer {\"ok\": true}."}]}
```

## Add your own
Add an entry to your project's `.claude/settings.json` (it applies next to the plugin's hooks):
```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "prompt", "if": "Bash(rm *)",
  "prompt": "Hook input: $ARGUMENTS\nBlock deleting anything outside the project's tmp/ or qa-runs/ folders. Answer {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."}]}]}}
```

## Limits (be honest about them)
- A `prompt` hook sees the hook input only, not the conversation. Rules about approvals use `agent` hooks, which read `transcript_path`; that file is written asynchronously and can lag the current turn by a moment.
- Model judgement is not a security boundary. Hard limits belong in permission rules (`deny`) and in the scripts (ShipShape's scripts enforce allow-lists, never-pay, stop-before-input and desktop gates themselves).
- `if` matching on Bash and PowerShell is best-effort (wildcards over the command text). Every Bash guard is mirrored under the `PowerShell` matcher, because Windows sessions often use the PowerShell tool.
- The commit-scan command hook is written for a POSIX shell. Claude Code runs command hooks through Git Bash on Windows when it is installed (it normally is); without Git Bash that one hook cannot run, so install Git for Windows.
