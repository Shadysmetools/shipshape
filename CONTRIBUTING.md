# Contributing to ShipShape

Thanks for improving ShipShape. Most contributions come from a team copy (a fork or a team branch, see [docs/TEAM-SETUP.md](docs/TEAM-SETUP.md)). Send an improvement back upstream when it helps every user, not just your team.

## Before you start
- Look for an existing issue. If there isn't one, open it first: one problem per issue. From any Claude Code session, `/qa-issue` drafts one with privacy-filtered logs and files it only after you say yes.
- The license is not chosen yet (`plugin.json` says `UNLICENSED`, see [LICENSE-OPTIONS.md](LICENSE-OPTIONS.md)). By opening a PR you agree that the maintainer may ship your contribution under the license that the owner picks.

## Make the change
1. Branch from the upstream default branch in your fork: `git checkout -b fix/<short-name>`.
2. Keep team-only things out of the change: your `qa.config.yaml`, client or people names, internal URLs, prices, and keys. ShipShape ships no keys, and none may be added anywhere in the repo.
3. Scripts (`scripts/*.py`) are deterministic and tested. A behaviour change comes with a test in `tests/`, and a bug fix comes with a test that fails without the fix.
4. Agents, commands and skills need front matter with a `description` of more than 40 characters, and every `${CLAUDE_PLUGIN_ROOT}/...` path they mention must exist. `tests/test_workflows_and_manifests.py` checks both.
5. Write docs in plain English with short sentences. Keep real timings and counts honest.
6. Add a line under `## Unreleased` in `CHANGELOG.md`.

## Check before you push
```bash
PYTHONIOENCODING=utf-8 python -m pytest -q -p no:cacheprovider    # all green
python scripts/privacy.py scan <every file you changed>            # 0 findings
claude plugin validate .                                           # if Claude Code is installed
```
The commit hook blocks staged secrets and personal data. Don't skip it.

## Open the pull request
- Open the PR from your fork's branch to `Shadysmetools/shipshape`. Never push to `main` (the hook guard blocks it).
- In the body, say what changed and why, link the issue (`Closes #N`), and add an **Evidence** section: the test counts, and the command output or report that shows the change working.
- The maintainer reviews and merges. Contributors don't merge their own PRs.

## Conduct
Be kind and specific, and review the code, not the person.
