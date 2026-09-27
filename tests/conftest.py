from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_demo_db import build  # noqa: E402

from copiloto.bootstrap import build_app  # noqa: E402


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("db") / "demo_synthetic_bank.db")


@pytest.fixture()
def app(demo_db, tmp_path):
    return build_app(db_path=demo_db, audit_path=tmp_path / "audit.db", secret=b"segredo-de-teste")


@pytest.fixture()
def session_a(app):
    """Sessão da analista A (EMP-001)."""
    return app.new_session("EMP-001")


@pytest.fixture()
def session_b(app):
    """Sessão do analista B (EMP-002)."""
    return app.new_session("EMP-002")
