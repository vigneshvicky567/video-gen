"""Datadog agentless metrics — no-op safety + payload shape (no network)."""
from app import metrics
from app.config import settings


def test_emit_noop_without_key(monkeypatch):
    monkeypatch.setattr(settings, "DD_API_KEY", "")
    assert metrics.emit("manim.job.dispatched") is False   # no key -> no-op, no exception


def test_build_payload_shape(monkeypatch):
    monkeypatch.setattr(settings, "DD_SERVICE", "svc")
    monkeypatch.setattr(settings, "DD_ENV", "test")
    p = metrics._build_payload("manim.job.dispatched", 1, ["a:b"], "count", now=100)
    s = p["series"][0]
    assert s["metric"] == "manim.job.dispatched"
    assert s["type"] == 1                                  # count
    assert s["points"] == [{"timestamp": 100, "value": 1.0}]
    assert "a:b" in s["tags"] and "service:svc" in s["tags"] and "env:test" in s["tags"]


def test_emit_swallows_errors(monkeypatch):
    monkeypatch.setattr(settings, "DD_API_KEY", "ddkey")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(metrics.httpx, "post", boom)
    assert metrics.emit("x") is False                      # never raises into the request path
