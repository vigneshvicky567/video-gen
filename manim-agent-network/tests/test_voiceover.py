from unittest.mock import patch

from fastapi.testclient import TestClient

from services.voiceover.app.main import app


client = TestClient(app)


def test_voiceover_uses_kokoro(tmp_path):
    def fake_kokoro(text, output_path):
        path = tmp_path / "scene_1_audio.wav"
        path.write_bytes(b"audio")
        return True, ""

    with (
        patch("services.voiceover.app.main.settings") as mock_settings,
        patch("services.voiceover.app.main.generate_kokoro_tts", side_effect=fake_kokoro),
    ):
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.VOICEOVER_PROVIDER = "kokoro"
        mock_settings.VOICEOVER_MAX_RETRIES = 3
        mock_settings.VOICEOVER_RETRY_BACKOFF_SECONDS = 0

        response = client.post(
            "/generate",
            json={"job_id": "job1", "scene_id": 1, "narration_text": "Hello"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider_used"] == "kokoro"
    assert data["fallback_used"] is False


def test_voiceover_retries_then_succeeds(tmp_path):
    """Kokoro fails once, succeeds on the second attempt — no fallback engine."""
    calls = {"n": 0}

    def flaky_kokoro(text, output_path):
        calls["n"] += 1
        if calls["n"] < 2:
            return False, "transient failure"
        path = tmp_path / "scene_1_audio.wav"
        path.write_bytes(b"audio")
        return True, ""

    with (
        patch("services.voiceover.app.main.settings") as mock_settings,
        patch("services.voiceover.app.main.generate_kokoro_tts", side_effect=flaky_kokoro),
    ):
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.VOICEOVER_PROVIDER = "kokoro"
        mock_settings.VOICEOVER_MAX_RETRIES = 3
        mock_settings.VOICEOVER_RETRY_BACKOFF_SECONDS = 0

        response = client.post(
            "/generate",
            json={"job_id": "job1", "scene_id": 1, "narration_text": "Hello"},
        )

    assert response.status_code == 200
    assert response.json()["provider_used"] == "kokoro"
    assert calls["n"] == 2


def test_voiceover_fails_after_exhausting_retries(tmp_path):
    with (
        patch("services.voiceover.app.main.settings") as mock_settings,
        patch("services.voiceover.app.main.generate_kokoro_tts", return_value=(False, "missing model")),
    ):
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.VOICEOVER_PROVIDER = "kokoro"
        mock_settings.VOICEOVER_MAX_RETRIES = 2
        mock_settings.VOICEOVER_RETRY_BACKOFF_SECONDS = 0

        response = client.post(
            "/generate",
            json={"job_id": "job1", "scene_id": 1, "narration_text": "Hello"},
        )

    assert response.status_code == 500
    assert "Voiceover failed" in response.json()["detail"]