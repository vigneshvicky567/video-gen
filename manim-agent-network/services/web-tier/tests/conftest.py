import os
import sys
import pathlib

# put services/web-tier on the path so `import app...` works
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from app import db, main, dispatch, analyze
from app.auth import Principal, get_principal


# current test principal (mutated by helpers below)
_CURRENT = {"p": Principal(clerk_id="user_a", role="user", email="a@x.com")}


def _fake_principal():
    return _CURRENT["p"]


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.set_engine(f"sqlite:///{tmp_path / 'test.db'}")
    # default: dispatch "succeeds" without hitting GitHub
    monkeypatch.setattr(dispatch, "dispatch_render", lambda job_id: (True, 204))
    monkeypatch.setattr(analyze, "analyze_topic",
                        lambda topic, client=None: {"feasible": True, "suggested_duration_seconds": 90})
    _CURRENT["p"] = Principal(clerk_id="user_a", role="user", email="a@x.com")
    yield


@pytest.fixture
def as_user():
    def _set(clerk_id="user_a", role="user"):
        _CURRENT["p"] = Principal(clerk_id=clerk_id, role=role, email=f"{clerk_id}@x.com")
    return _set


@pytest.fixture
def client():
    """Authenticated client (auth dependency overridden to _CURRENT principal)."""
    main.app.dependency_overrides[get_principal] = _fake_principal
    c = TestClient(main.app)
    yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def raw_client():
    """No auth override — exercises the real Clerk-gated path (expects 401)."""
    main.app.dependency_overrides.clear()
    return TestClient(main.app)
