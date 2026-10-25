# Team setup: one person customises, the team installs and updates

One person (the team lead) keeps a team copy of ShipShape. Teammates install from that copy and get the lead's changes as updates. Fixes from upstream (`Shadysmetools/shipshape`) are pulled into the team copy, and improvements go back upstream as pull requests.

> **Keys.** ShipShape provides no API keys or third-party accounts; each user supplies their own, stored only on their computer; third-party costs and accounts are the user's responsibility. A team copy never contains keys either: `qa.config.yaml` holds key *names* only, and each teammate runs `/qa-setup` (or `python scripts/keys.py set <NAME>`) on their own machine.

Sources for the plugin behaviour below (Claude Code docs, checked 25 Oct 2026):
- [Install and manage plugins](https://code.claude.com/docs/en/plugins/install.md): marketplace sources, `#ref`, auto-update, update commands.
- [Host and maintain a marketplace](https://code.claude.com/docs/en/plugins/host-marketplace.md): "Keep users up to date" and "Release a new version".
- [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference.md): one marketplace per `name`.
- [Subagents](https://code.claude.com/docs/en/sub-agents.md): which agent definition wins when names clash.

## 1. Make the team copy (team lead, once)

Pick one:
- **A fork**: fork `Shadysmetools/shipshape` to `<your-org>/shipshape`. Use this when the team wants its own issues and PRs.
- **A branch**: a long-lived branch such as `team/<your-team>` in a repo you can push to. This is lighter, but it needs push access to that repo.

The marketplace name comes from `.claude-plugin/marketplace.json` (`"name": "shipshape"`), not from the repo name. So a fork still installs as `smetools-agent-kit@shipshape`. Each user can register only one marketplace per name. A teammate who already added upstream `shipshape` removes it first: `/plugin marketplace remove shipshape`.

## 2. Teammates install

Inside Claude Code:
```
/plugin marketplace add <your-org>/shipshape                  # a fork, default branch
/plugin marketplace add <your-org>/shipshape#team/<your-team> # a branch or tag: add #ref
/plugin install smetools-agent-kit@shipshape
```
A branch or tag is pinned with **`#ref`**, not `@branch`: "`owner/repo`. Add `#ref` to pin a branch or tag", for example `/plugin marketplace add your-org/plugins#v1.2.0` (install.md). The `@` belongs to the install id (`<plugin>@<marketplace>`). Any git host works with the full clone URL plus `#ref`. A private repo uses the teammate's own git credentials (SSH key or HTTPS).

Then each teammate runs the installer once (`bash bin/install.sh` or `bin\install.ps1`) and `/qa-setup` in their project for their own keys.

## 3. Ship a change to the team (team lead)

**Bump `version` in `.claude-plugin/plugin.json` on every change you want teammates to receive.** Teammates "get a new copy only when the plugin's computed version differs from the one they have. … If you set `"version": "1.0.0"` and push new commits without changing it, users don't receive them" (host-marketplace.md, "Release a new version"). Use a team suffix so you never collide with an upstream number, for example `0.1.1-team.3`.

The version lives in `plugin.json` only. The marketplace entry doesn't repeat it, because the docs say: "Don't set `version` in both `plugin.json` and the marketplace entry".

Then: commit, run `python -m pytest`, and push to the team fork or branch.

## 4. Teammates update

Auto-update is **off by default** for third-party marketplaces like this one (install.md, "On by default … Off by default: every other marketplace"). Each teammate picks one:
- **Automatic**: `/plugin` → **Marketplaces** → `shipshape` → **Enable auto-update**. After a session starts, Claude Code refreshes the marketplace and updates the plugin on disk.
- **By hand**: `claude plugin update smetools-agent-kit@shipshape` in a shell, or `/plugin` → **Marketplaces** → `shipshape` → **Update marketplace**. Note that `claude plugin marketplace update` with no name refreshes the listing only, and leaves installed plugins at their current versions.

A running session keeps the version it loaded. After an update, run `/reload-plugins` or start a new session. If an update brings new Python packages, run the installer again.

A teammate who works from a local clone (`/plugin marketplace add /path/to/shipshape`) loads the files in place: `git pull`, then `/reload-plugins`. No version bump is needed for that teammate.

## 5. Pull upstream fixes into the team copy (team lead)

```bash
git remote add upstream https://github.com/Shadysmetools/shipshape.git   # once
git fetch upstream
git checkout -b sync/upstream-YYYY-MM-DD
git merge upstream/main          # ShipShape's hook guard asks you to approve merges
python -m pytest                 # must stay green
```
Open a PR from the sync branch into the team branch, merge it, then bump the team `version` (step 3) so teammates receive it. Read `CHANGELOG.md` for anything that changes config keys.

## 6. Customise without merge conflicts

Upstream updates conflict only where you edited upstream files. So keep team changes in places that upstream never edits:

| What to change | Where | Why it doesn't conflict |
|---|---|---|
| URLs, hosts, voice, loop limits, delivery channels, Odoo stages, the timesheet rule, where `/qa-issue` files (`issues.repo`) | `qa.config.yaml` in each **project** (copied from `templates/qa.config.example.yaml`) | It lives in your project, not in the plugin |
| A different persona or extra rules for an agent | your own agent file in the project's `.claude/agents/` (check it in) | Project agents sit outside the plugin. On a name clash, Claude Code uses the higher-priority one, and project `.claude/agents/` (priority 3) beats a plugin's `agents/` (priority 5), per sub-agents.md |
| Private names for the privacy filter | a deny-list file outside the repo (`SMEKIT_DENYLIST`) | Never committed |
| Keys | each user's keychain or `~/.config/shipshape/secrets/` (via `keys.py`) | Never committed |

A limit to know about: the bundled workflows (`workflows/*.workflow.js`) call agents by their **scoped** name, such as `smetools-agent-kit:qa-automation-tester`, so a project agent with the same bare name doesn't replace them inside a workflow run. A same-name project agent applies where an agent is asked for by its bare name. If the team needs a different agent inside the workflow, give your agent its own name (for example `team-qa-lead`) and ask for it by that name, or change the plugin file and send the change upstream (step 7).

If you must edit a plugin file in the team copy, keep the edit small and in its own commit, and send it upstream (step 7), so that the next sync removes the difference instead of conflicting with it.

## 7. Contribute back

Improvements made in the team copy come back as a pull request to `Shadysmetools/shipshape`, from a branch in the team fork. See [CONTRIBUTING.md](../CONTRIBUTING.md). Keep team-only settings (your config, names, URLs) out of the PR.

## 8. Report a problem from the field

Any teammate's session can file a ShipShape bug with `/qa-issue`. It shows a privacy-filtered preview first and files only after the user says yes. Point `issues.repo` at the team fork if the lead wants to triage first.
