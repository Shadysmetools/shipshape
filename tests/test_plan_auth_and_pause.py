"""Plan-level auth (local_storage) for signed-in staging runs."""
import json

import pytest

import record


def test_local_storage_env_and_literal(monkeypatch):
    monkeypatch.setenv("QA_TOKEN", "secret-abc")
    got = record.resolve_local_storage({"local_storage": {"tok": {"env": "QA_TOKEN"}, "plain": "x", "obj": {"a": 1}}})
    assert got == {"tok": "secret-abc", "plain": "x", "obj": json.dumps({"a": 1})}


def test_local_storage_missing_env_names_variable(monkeypatch):
    monkeypatch.delenv("NOPE_TOKEN", raising=False)
    with pytest.raises(record.PlanError, match="NOPE_TOKEN"):
        record.resolve_local_storage({"local_storage": {"t": {"env": "NOPE_TOKEN"}}})


def test_local_storage_file_json_path(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"a": {"b": "deep"}}))
    assert record.resolve_local_storage({"local_storage": {"k": {"file": str(f), "json": "a.b"}}}) == {"k": "deep"}


def test_script_is_origin_scoped():
    js = record.local_storage_script("https://x.test", {"k": "v"})
    assert 'location.origin !== "https://x.test"' in js and '"k": "v"' in js
