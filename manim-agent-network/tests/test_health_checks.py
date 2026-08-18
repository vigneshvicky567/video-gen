"""Smoke tests: hit /health on every service via TestClient (no Docker needed)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def orchestrator_client():
    from services.orchestrator.app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def script_writer_client():
    from services.script_writer.app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def code_generator_client():
    from services.code_generator.app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def validator_client():
    from services.validator.app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def voiceover_client():
    from services.voiceover.app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def compositor_client():
    from services.compositor.app.main import app
    return TestClient(app)


def test_voiceover_health(voiceover_client):
    r = voiceover_client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_validator_health(validator_client):
    r = validator_client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_compositor_health(compositor_client):
    r = compositor_client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") in ("ok", "healthy")
