-- <your_module>: a neutralized copy (staging, a duplicated database, `odoo-bin neutralize`) must send NOTHING live.
-- Odoo runs data/neutralize.sql of every installed module when a database is neutralized.
-- NEVER list this file in the manifest 'data': it would switch production off on its own upgrade.
-- Pair it with: crons in noupdate="1" blocks, a registry hook that re-applies this on a neutralized DB,
-- and a runtime guard in every sender (database.is_neutralized / production uuid check).

-- 1. Every outbound connection of this module off.
UPDATE your_module_config SET enabled = false WHERE enabled IS TRUE;

-- 2. This module's crons off (noupdate keeps them off across upgrades).
UPDATE ir_cron SET active = false
 WHERE active IS TRUE
   AND id IN (SELECT res_id FROM ir_model_data
              WHERE model = 'ir.cron' AND module = 'your_module');

-- 3. Custom "production mode" flags that Odoo's own neutralization does not know about.
UPDATE ir_config_parameter SET value = 'test' WHERE key = 'your_module.environment';
