# -*- coding: utf-8 -*-
"""migrations/<series>.<x>.<y>.<z>/post-migration.py - idempotent and guarded.

Rules:
- Ask whether the COLUMNS you read and write exist, not whether the table exists:
  core tables (sale_order, pos_order, ...) always exist; columns added by an optional
  adapter module may not. A failed migration fails the whole build.
- Safe to run twice: WHERE clauses skip rows already migrated.
- No DROP without IF EXISTS; no INSERT without a uniqueness guard.
- On a neutralized copy, skip anything that would queue live sends.
"""
import logging

_logger = logging.getLogger(__name__)
COLUMNS = ("new_flag", "old_sent")  # every column this script touches


def _has_columns(cr, table, columns=COLUMNS):
    cr.execute(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s AND column_name IN %s""",
        (table, tuple(columns)),
    )
    return cr.fetchone()[0] == len(columns)


def _neutralized(cr):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized'")
    row = cr.fetchone()
    return bool(row and row[0] and row[0].lower() in ("1", "true"))


def migrate(cr, version):
    if not version:  # fresh install: nothing to migrate
        return
    for table in ("sale_order", "pos_order"):
        if not _has_columns(cr, table):
            _logger.info("%s: columns not present, skipped", table)
            continue
        cr.execute(
            "UPDATE {t} SET new_flag = TRUE WHERE new_flag IS NOT TRUE AND old_sent IS TRUE".format(t=table)  # idempotent
        )
        _logger.info("%s: %s row(s) marked", table, cr.rowcount)
    if _neutralized(cr):
        _logger.info("neutralized database: re-queue skipped")
