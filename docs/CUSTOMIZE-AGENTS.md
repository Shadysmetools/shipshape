# Customize the crew: your own agents in kit roles, and agents the crew can ask

ShipShape's QA lead dispatches **roles** ("the Odoo expert role", "the refuter role"), not agent files. Each role is
filled by the kit's agent unless your project says otherwise. You can:

1. **Replace a kit agent** with your own (for example your Odoo functional consultant instead of `odoo-expert`).
2. **Register external agents** the crew may **ask** when the expected behaviour is unclear (a ticket analyst, an
   Odoo consultant, an internal developer). Every question and answer is kept in the run's ledger.

Both live in your project (`.claude/agents/` and `qa.config.yaml`), not in the plugin, so a plugin update never
overwrites them and you never fork the plugin.

## Roles

| Role | Kit agent |
|---|---|
| `code-reviewer` | `qa-code-reviewer` |
| `security-reviewer` | `qa-security-reviewer` |
| `automation-tester` | `qa-automation-tester` |
| `load-tester` | `qa-load-tester` |
| `live-regression` | `qa-live-regression-recorder` |
| `desktop-tester` | `qa-desktop-tester` |
| `demo-video` | `qa-demo-video-producer` |
| `refuter` | `qa-refuter` |
| `odoo-expert` | `odoo-expert` |
| `timesheet` | `timesheet-agent` |

See who fills each role in your project:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/crew.py roles --config qa.config.yaml
```

A role resolves in this order, first hit wins:

1. `agents.roles.<role>` in `qa.config.yaml`.
2. A project agent in `.claude/agents/` whose `name` is the kit agent's name (for example `name: odoo-expert`).
3. The kit's agent, under its plugin-scoped name `smetools-agent-kit:<agent>`.

## Why a role map and not only a same-name file

Claude Code's own rule, from the subagents docs ([code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents),
"Choose the subagent scope"): *"When multiple subagents share the same name, Claude Code uses the one from the
higher-priority location."* Project agents (`.claude/agents/`, priority 3) beat user agents (`~/.claude/agents/`, 4),
which beat plugin agents (5, lowest).

The same page also says plugin agents are registered under a **scoped** name: they appear *"under their scoped name"*,
such as `my-plugin:code-reviewer`, and *"Names can't contain `:`, which is reserved for plugin-scoped identifiers"*.
ShipShape's workflows call agents by their scoped name (`smetools-agent-kit:odoo-expert`), so that a same-named agent
from another plugin can never be picked by accident. The docs do not say that a project agent named `odoo-expert`
replaces a call to `smetools-agent-kit:odoo-expert`. So the kit does not rely on that: `crew.py` finds your
same-name project agent itself (step 2 above) and hands its bare name to the QA lead and the workflows. When you ask
for the agent by its bare name in a normal conversation ("use the odoo-expert agent"), the precedence rule above applies too.

## Worked example: your own Odoo functional consultant instead of `odoo-expert`

**1. Write the agent** in your project, `.claude/agents/odoo-functional-consultant.md`:

```markdown
---
name: odoo-functional-consultant
description: Our Odoo functional consultant. Use for expected Odoo behaviour (invoicing, stock, accounting flows),
  module reviews and Odoo deploy checks in this project. Knows our configuration and our customers' processes.
tools: Read, Grep, Glob, Bash
model: inherit
---
You are the team's Odoo functional consultant. Answer from our process docs in docs/odoo/ first, then from standard
Odoo 17 behaviour; say which. Production is read-only. Keep answers to 5 lines and quote the source.
```

**2. Put it in the role**, in `qa.config.yaml`:

```yaml
agents:
  roles:
    odoo-expert: odoo-functional-consultant
```

(Or skip this step and name your file's agent `odoo-expert`: step 2 of the resolution order picks it up.)

**3. Check it:**

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/crew.py resolve odoo-expert --config qa.config.yaml
# odoo-functional-consultant
```

From then on, when the QA lead needs the Odoo expert role it dispatches `odoo-functional-consultant`, and `/qa-goal`
passes the same map to the workflows (`args.agents`). Remove the line to go back to the kit's agent.

## External agents the crew can ask

When the expected result of a test is not written in the ticket or spec, the refuter used to have only one honest
answer: "inconclusive". Now the crew can ask an agent that knows. Register them in `qa.config.yaml`:

```yaml
agents:
  external:
    - name: odoo-consultant
      role: odoo-expert
      when: expected Odoo behaviour (accounting, stock, invoicing flows) is not written in the ticket
      subagent: odoo-functional-consultant    # a Claude Code agent name
    - name: ticket-analyst
      role: ticket-analyst
      when: the acceptance criteria of a ticket are missing or contradict each other
      session: ticket-analyst                 # a running Claude Code session, reached with SendMessage
    - name: internal-dev
      role: developer
      when: a failure might be intended behaviour of a recent change
      command: [python, tools/ask_dev.py]     # question on stdin, answer on stdout
```

Each entry needs `name`, `role`, `when` and exactly one way to reach it:

| Field | How the crew reaches it | Who can ask |
|---|---|---|
| `subagent: <name>` | dispatches that Claude Code agent with the question | QA lead; the full-qa workflow does it for the refuter |
| `session: <name>` | `SendMessage` to that Claude Code session, then waits for the reply | QA lead |
| `command: <argv>` | `crew.py ask <name> --question "..."`: runs the command (no shell), question on stdin, answer from stdout, 300 s timeout | QA lead and refuter |

The refuter only has `Read, Grep, Glob, Bash`, so it cannot dispatch a subagent or message a session. For those, it
returns `VERDICT: inconclusive` with a `QUESTION for <role>: ...` line; the QA lead asks, records the answer and sends
the claim back to the refuter. In the full-qa workflow this happens automatically for `subagent` entries; questions
for `session`/`command` entries come back in the workflow result as `openQuestions`.

**No secrets in this section.** ShipShape ships no API keys and holds none. If an external agent needs credentials,
its own command reads them on its own machine.

### Every question goes in the ledger

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_loop.py consult --agent odoo-consultant --via subagent --id B2 --by qa-refuter \
  --question "Should a posted invoice still be editable?" --answer "No: posted invoices are locked; reset to draft first."
```

This adds `{id: Q1, agent, via, question, answer, bug, by, at}` to `ledger.json` `consults`, appends a line to bug B2's
history, and shows up in the HTML report under "Questions asked to other agents". An answer is a source the refuter
quotes, not a verdict: the two-agent bar still decides whether a bug is filed.

### Handing findings back

At the end of a run the QA lead sends the report path and the verdict on each bug it asked about back to the agent
it consulted, by the same route.

## Keeping it across plugin updates

`.claude/agents/` and `qa.config.yaml` are in your repository. A plugin update replaces only the plugin's own
folder, so your agents and the role map stay as they are. If a kit role is renamed in a release, the CHANGELOG says
so, and `crew.py roles` fails with `config error at agents.roles.<role>: unknown role` until you rename it.
