#!/usr/bin/env python3
"""Fake, deterministic fixtures for the tutorial (no real people, clients or logs).

    python make_fixtures.py <out_dir>

Writes:
  <out>/fake-claude-project/*.jsonl   synthetic Claude Code transcripts (2 days, 1 subagent)
  <out>/tasks.json                    task rules for /timesheet (fake project + employee)
  <out>/demo_shop_loyalty/            a small fake Odoo 17 module with a few deliberate issues
"""
import datetime as dt
import json
import os
import sys

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "fixtures")
TZ = dt.timezone(dt.timedelta(hours=2))


def ts(day, hh, mm):
    return dt.datetime(2026, 10, day, hh, mm, tzinfo=TZ).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def session(path, day, start, minutes, step, prompts):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows, t0 = [], dt.datetime(2026, 10, day, *start, tzinfo=TZ)
    for i, m in enumerate(range(0, minutes + 1, step)):
        t = (t0 + dt.timedelta(minutes=m)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        if i < len(prompts):
            rows.append({"type": "user", "timestamp": t, "message": {"role": "user", "content": prompts[i]}})
        else:
            rows.append({"type": "assistant", "timestamp": t, "message": {"role": "assistant", "content": "ok"}})
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")


proj = os.path.join(OUT, "fake-claude-project")
session(os.path.join(proj, "s-0001.jsonl"), 19, (9, 0), 110, 4,
        ["fix the signup form validation on the demo shop", "add a test for the empty name case"])
session(os.path.join(proj, "s-0001", "subagents", "a-01.jsonl"), 19, (9, 30), 40, 3, ["run the signup tests twice"])
session(os.path.join(proj, "s-0002.jsonl"), 19, (14, 0), 75, 5, ["load test the checkout page with the smoke profile"])
session(os.path.join(proj, "s-0003.jsonl"), 20, (10, 15), 95, 5,
        ["review the loyalty points module before staging", "write the migration for loyalty points"])
session(os.path.join(proj, "s-0004.jsonl"), 20, (16, 0), 12, 4, ["build my timesheet for this week"])

json.dump({
    "project": {"id": 7, "name": "Demo Shop"},
    "employee": {"id": 42, "name": "Sam Example"},
    "tasks": [
        {"id": 101, "name": "Sign-up form", "match": ["signup", "sign-up", "empty name"]},
        {"id": 102, "name": "Checkout load test", "match": ["load test", "checkout"]},
        {"id": 103, "name": "Loyalty points module", "match": ["loyalty"]},
    ],
    "exclude": ["timesheet"],
}, open(os.path.join(OUT, "tasks.json"), "w"), indent=1)

mod = os.path.join(OUT, "demo_shop_loyalty")
for sub in ("models", "data", "views"):
    os.makedirs(os.path.join(mod, sub), exist_ok=True)
open(os.path.join(mod, "__init__.py"), "w").write("from . import models\n")
open(os.path.join(mod, "__manifest__.py"), "w").write(
    "{\n    'name': 'Demo Shop Loyalty',\n    'version': '17.0.1.0.1',\n    'license': 'LGPL-3',\n"
    "    'depends': ['base'],\n    'data': ['data/cron.xml', 'views/points_views.xml'],\n}\n")
open(os.path.join(mod, "models", "__init__.py"), "w").write("from . import points\n")
open(os.path.join(mod, "models", "points.py"), "w").write(
    "from odoo import fields, models\n\n\nclass LoyaltyPoints(models.Model):\n    _name = 'demo.loyalty.points'\n"
    "    _description = 'Loyalty points (demo)'\n\n    partner_id = fields.Many2one('res.partner')\n    points = fields.Integer()\n\n"
    "    def _cron_expire(self):\n        self.search([('points', '<', 0)]).unlink()\n        self.env.cr.commit()\n")
open(os.path.join(mod, "data", "cron.xml"), "w").write(
    "<odoo>\n  <record id=\"cron_expire_points\" model=\"ir.cron\">\n    <field name=\"name\">Expire demo points</field>\n"
    "    <field name=\"model_id\" ref=\"model_demo_loyalty_points\"/>\n    <field name=\"code\">model._cron_expire()</field>\n"
    "    <field name=\"interval_type\">days</field>\n  </record>\n</odoo>\n")
open(os.path.join(mod, "views", "points_views.xml"), "w").write(
    "<odoo>\n  <record id=\"view_points_tree\" model=\"ir.ui.view\">\n    <field name=\"model\">demo.loyalty.points</field>\n"
    "    <field name=\"arch\" type=\"xml\"><tree><field name=\"partner_id\"/><field name=\"points\"/></tree></field>\n  </record>\n</odoo>\n")
print("fixtures in", OUT)
