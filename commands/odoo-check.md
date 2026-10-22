---
description: Pre-deploy check of an Odoo module - version bump, guarded idempotent migrations, noupdate crons, neutralize.sql, no cr.commit, tests, API level - plus the odoo-expert's review.
argument-hint: "<module path> [base ref, e.g. origin/<staging-branch>] [series 17.0]"
---
Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/odoo_check.py <module> --base <base> --series <series>` with: $ARGUMENTS. Then have the `odoo-expert` agent review the FAIL/WARN lines and the diff against `${CLAUDE_PLUGIN_ROOT}/docs/ODOO-PLAYBOOK.md`. Report `N pass / M fail / W warn` and the fixes needed before the deploy.
