# ShipShape for buyers

> **Draft.** The license, pricing and commercial terms are not set yet. The owner sets them (see [LICENSE-OPTIONS.md](../LICENSE-OPTIONS.md)). Nothing on this page is an offer.

## What ShipShape does for you

ShipShape is a Claude Code plugin that runs a QA team on your own computer. You describe a goal in one sentence, for example `/qa-goal "a new user can sign up and reach checkout"`, and it:

- plans the test scenarios and reviews the code and security;
- runs every scenario twice in a real browser, so a flaky result is never reported as a pass;
- records narrated videos with captions as evidence;
- tries to disprove every failure before filing it, and re-tests after fixes;
- writes an offline HTML report, and can send it to Telegram, WhatsApp, Slack or email (always a dry run until you say "send").

It also ships a timesheet agent, which measures real working hours from Claude Code logs, and an Odoo expert with safe staging and deploy rules.

## How you install it

Requirements: [Claude Code](https://code.claude.com), Python 3.10+, Node.js 20+ and ffmpeg. A first install takes about 20 minutes, mostly for the Chromium download.

1. Get the repository: your copy, or the marketplace you were given access to.
2. Run the installer: `bash bin/install.sh` (macOS / Linux / Git Bash) or `powershell -ExecutionPolicy Bypass -File bin\install.ps1` (Windows). Check the result with `bash bin/doctor.sh`.
3. In Claude Code, run `/plugin marketplace add <the repo you were given>`, then `/plugin install smetools-agent-kit@shipshape`.
4. In your project, run `/qa-setup`. It is a short interview: URLs, voice, video length, delivery channels, and your own keys.
5. Try the demo with `bash bin/run-qa.sh demo` (fake data only), then run your first `/qa-goal`.

Teams follow [TEAM-SETUP.md](TEAM-SETUP.md): one person keeps the team copy, and everyone else installs and updates from it.

## Keys and third-party accounts

ShipShape provides no API keys or third-party accounts; each user supplies their own, stored only on their computer; third-party costs and accounts are the user's responsibility.

That covers voices (ElevenLabs, OpenAI), delivery channels (Telegram, WhatsApp, Slack, email), Odoo and any other service you connect. ShipShape saves keys in the OS keychain or in `~/.config/shipshape/secrets/` on your machine, never in the project or the repository. The free edge-tts voice needs no key.

## Support boundaries

Our responsibility ends at setup. To be decided by the owner per tier, but the line is:

| In scope | Out of scope |
|---|---|
| Installing the plugin and getting `bin/doctor` green | Third-party accounts, keys, quotas and bills |
| `/qa-setup` and a first working `/qa-goal` on your staging site | Fixing bugs in your application |
| Bugs in ShipShape itself (file them with `/qa-issue`) | Testing production with real customer data or payments (ShipShape refuses this by design) |
| Explaining the reports, rules and hooks | Hosting, CI servers or machines we don't control |

## What's included by tier

**pricing: owner to set.** This table is a placeholder: the tiers, contents and prices are not decided.

| | Starter | Team | Managed |
|---|---|---|---|
| Who it's for | one user | a team sharing one customised copy | a team that wants it run for them |
| The plugin (agents, commands, scripts, hooks) | yes | yes | yes |
| Team fork and update flow ([TEAM-SETUP.md](TEAM-SETUP.md)) | - | yes | yes |
| Setup help | owner to set | owner to set | owner to set |
| Support channel and response time | owner to set | owner to set | owner to set |
| Scheduled runs and report delivery set up for you | - | - | owner to set |
| Price | owner to set | owner to set | owner to set |

## What stays internal

These are not part of the product, and they are never shipped or shared:
- our API keys and accounts (there are none in the product, see above);
- the private deny-list of client and people names that the privacy filter uses;
- other clients' configs, run folders, reports, videos and timesheets;
- internal planning notes and commercial terms.

## Safety you can rely on

The product works on test data only, never pays, stops before any input on live sites, and blocks hosts that are not allow-listed. A PASS without evidence counts as BLOCKED. Outward sends and writes need the owner's own approval in the conversation. See [OPERATING-RULES.md](OPERATING-RULES.md).
