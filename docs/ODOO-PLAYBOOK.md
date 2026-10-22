# Odoo playbook (17.0 to 20.0)

## Safe read/write discipline (MCP or RPC)
- Production is read-only unless the owner says otherwise in the conversation for one named action. A relayed approval is not approval; quote the owner's words.
- Read first: search/read the exact records, check who you are (which user, which companies you can see), then show the exact writes (model, ids, values) and wait for the OK. Write, then read back.
- Check access before planning a write: an import "under the developer" landed on the wrong company's employee once because the API user could only see one company.
- Change only what was asked. Test data only. One named contact speaks to a partner.
- RPC: `POST /web/dataset/call_kw` (or `/json/2/` on newer series) with the model, method, args and kwargs; never store session cookies or API keys in files that get committed.
- Never hard-code record ids in test scripts; re-resolve after every database refresh.

## Module layout
```
your_module/
  __manifest__.py        version <series>.<major>.<round>.<patch>, license, depends only on modules installed in production
  lib/                   pure payload builders + HTTP client (unit-tested without Odoo)
  models/                config (per company), outbox queue, inbound event (_ingest + cron), senders with a staging guard
  controllers/           API-key / HMAC auth, real status codes, idempotency (unique key), logged refusal reasons
  data/ir_cron.xml       <data noupdate="1">
  data/neutralize.sql    NOT in the manifest data
  migrations/<version>/  guarded, idempotent post-migration
  tests/                 one TransactionCase file per round + shared base; HTTP mocked
```
Never outbound HTTP or `cr.commit()` inside a request or ORM hook: enqueue, and let a cron send after commit with retry/backoff. Always scope by `company_id`; `sudo()` crosses company isolation. Multi-company: new models get `company_id` and record rules.

## Versioning and commits
Bump the version on every code change (Odoo.sh upgrades only modules whose version went up). Commit prefixes `[ADD] [FIX] [UPD] [TEST] [DOC]` with "round NN". `scripts/odoo_check.py --base origin/<staging-branch>` fails when code changed without a bump.

## Migrations
Guard on `information_schema.columns` for the exact columns used; `IF EXISTS`/`IF NOT EXISTS`; idempotent WHERE clauses; skip live re-queues on a neutralized DB. Template: `templates/odoo/post-migration.py`. A failed migration fails the whole build and Odoo.sh keeps serving the previous build.

## Staging-copy safety
A staging build is a neutralized copy of production: real customer data, production credentials, crons off, mail servers removed. Neutralization alone is not trusted:
1. Odoo's neutralization + your `data/neutralize.sql`.
2. Crons in `noupdate="1"`, so `-u` never re-arms them.
3. A registry hook re-applies the switch-off on a neutralized DB (covers copies neutralized before your module existed).
4. A runtime guard in every sender: refuse when `database.is_neutralized` is set or the DB uuid differs from the recorded production uuid; log one line; leave the record untouched for production.
Plus allow-lists for any real recipient (an empty list blocks everyone), fixed at startup. Forward exactly the value you checked. Template: `templates/odoo/neutralize.sql`, runbook `templates/odoo/STAGING-RUNBOOK.md`.

## Odoo.sh deploy flow
Feature branch (its own development build, "specific list of modules", tests on module selection) → deliberate fast-forward into the staging branch → UAT on video → owner approval → production. Never push to production or another team's branch; never force-push; branch names are case-sensitive. Gotchas:
- Every push to a staging branch can create a NEW build and URL; a partner testing the old URL gets a 404. During partner tests, push to the dev branch only and say which link is current.
- "Update current build" keeps the database; a FRESH build brings a fresh copy and erases staging configuration and test data: keep the post-install configuration as a replayable script.
- In-place patches on a running build are wiped by a rebuild; commit promptly.
- Read `install.log` for "N tests, M failed"; Odoo stops after a few failures and the badge hides the count.
- Big-table install hooks can time out a build: batch them.
- Location/route rules can block a picking validation in staging data; check them before blaming your code.
- Staging builds expire: track the date.

## Promotion to production (one at a time)
1. Prepare and test the rollback first (previous build id or revert commit, and the data steps to undo).
2. Replay the change read-only against production data (a dry run or a read-only query of what would change).
3. Merge with the owner's approval, then hold a 60-minute watch (logs, error rate, the changed flow).
4. The next promotion waits until the watch has closed clean. Record the watch start and end in the run log.

## Tests
Failing-then-passing proof per bug (`templates/BUG-LOG.md`): push the test (red), then the fix (green). Inbound webhooks in live staging E2E: simulate by calling the model's ingest method from `odoo-bin shell`, and label those video scenes SIMULATED.

## Timesheets
`account.analytic.line` with `project_id`, `task_id`, `employee_id`, `unit_amount`, `name`, `date`. Use `scripts/timesheet.py`; check `allow_timesheets` on the project and that the task stage does not block entries.
