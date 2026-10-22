---
name: odoo-safe-dev
description: Check an Odoo module before deploy and follow safe Odoo practice - version bump, guarded migrations, noupdate crons, neutralize.sql, staging-copy safety, Odoo.sh flow, read-before-write through MCP. Use for "check this Odoo module before deploy", Odoo upgrades, migrations or staging questions.
---
# Odoo check
`python ${CLAUDE_PLUGIN_ROOT}/scripts/odoo_check.py <module> --series 17.0 --base origin/<staging-branch>` -> `N pass / M fail / W warn`.

Templates: `${CLAUDE_PLUGIN_ROOT}/templates/odoo/` (neutralize.sql, a guarded post-migration, the staging runbook).

Rules and the Odoo.sh flow: `${CLAUDE_PLUGIN_ROOT}/docs/ODOO-PLAYBOOK.md`. Production is read-only without the owner's direct OK.
