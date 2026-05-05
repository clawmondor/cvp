"""Tests for db.py dialect-aware engine configuration."""

from cvp.db import _is_sqlite_url


def test_is_sqlite_url_true_for_sqlite():
    assert _is_sqlite_url("sqlite:///./data/cvp.db") is True
    assert _is_sqlite_url("sqlite+pysqlite:///./data/cvp.db") is True


def test_is_sqlite_url_false_for_postgres():
    assert _is_sqlite_url("postgresql+psycopg://u:p@h/d") is False
    assert _is_sqlite_url("postgresql://u:p@h/d") is False
