# Staging upgrade runbook: <module> <old version> -> <new version>

A staging copy of production holds real customer data AND production credentials. Upgrading it must never send anything live.

## A. Pre-checks (Odoo.sh shell on the staging branch, `psql`)
```sql
-- 1. Must be true. No row or false: STOP, the copy is not neutralized.
SELECT key, value FROM ir_config_parameter
 WHERE key IN ('database.is_neutralized', 'database.uuid', '<module>.production_db_uuid');
-- 2. Module crons: every row active = f, noupdate = t.
SELECT d.module, d.name, c.active, d.noupdate FROM ir_cron c
  JOIN ir_model_data d ON d.model = 'ir.cron' AND d.res_id = c.id
 WHERE d.module LIKE '<module>%';
-- 3. Connections: note them; they must be disabled after the upgrade.
SELECT id, name, company_id, enabled FROM <module>_config;
-- 4. Versions before.
SELECT name, latest_version, state FROM ir_module_module WHERE name LIKE '<module>%';
```
An active cron in check 2: switch it off first, then re-run the check.

## B. Upgrade
- The branch reaches staging by a deliberate fast-forward (never force-push). Pushing is the owner's call.
- Odoo.sh upgrades modules whose version went up. Manual: `odoo-bin -d <db> -u <module> --stop-after-init` (only your module, never `-u all`).
- New `auto_install` modules are NOT installed by an upgrade of their dependency: check their state after.

## C. Post-checks
Re-run checks 1-4: still neutralized, crons off, connections off, versions as expected. Grep the build log: no request lines to live third-party APIs; "staging copy: not sent" lines are the guard working.

## D. Tests
```
odoo-bin -d <db> -u <module> --test-enable --test-tags /<module> --stop-after-init --http-port=8099 --log-level=test
```
Must end with `0 failed, 0 error(s)`. Report "N tests, M failed" from the log tail (save it as evidence). Select tests by module, not by tag, if not every file carries the tag.

## E. Partner tests
Partners test on ONE URL. On Odoo.sh every push to a staging branch can produce a new build URL: during a partner test, push to the dev branch only and tell the partner which link is current. In-place patches on a build are wiped by a rebuild: commit promptly. A FRESH build brings a fresh database: re-apply configuration from a script/checklist.
