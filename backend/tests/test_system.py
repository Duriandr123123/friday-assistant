import io
import wave
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.core.config import Settings
from backend.app.db import Recording
from backend.app.providers.base import ProviderError
from backend.app.providers.llm import validate_content
from backend.app.schemas import verbatim_content

TOKEN = "test-only-token-abcdefghijklmnopqrstuvwxyz"


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes(b"\0\0" * 3200)
    return output.getvalue()


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, api_token=TOKEN, data_directory=tmp_path / "data",
                    notes_directory=tmp_path / "notes", stt_provider="mock", llm_provider="mock",
                    retry_base_seconds=0)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, worker=False)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def upload(client, recording_id=None, audio=None):
    return client.post("/recordings", files={"file": ("test.wav", wav() if audio is None else audio, "audio/wav")},
        data={"recording_id": str(recording_id or uuid4()), "captured_at": "2026-09-08T23:35:00+05:00"})


def test_health_and_auth(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/notes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/openapi.json").status_code == 200


def test_e2e_audio_database_markdown_search(client, settings):
    response = upload(client)
    assert response.status_code == 202, response.text
    recording_id = response.json()["id"]
    assert client.app.state.processor.tick()
    record = client.get(f"/recordings/{recording_id}").json()
    assert record["status"] == "saved"
    assert record["processing_mode"] == "mock"
    assert "15 тысяч" in record["raw_transcript"]
    markdown = client.get(f"/notes/{recording_id}/markdown")
    assert markdown.status_code == 200
    assert "Исходная расшифровка" in markdown.text
    assert client.get("/notes?q=поставщик").json()[0]["id"] == recording_id
    assert len(list(settings.notes_directory.rglob("*.md"))) == 1
    assert client.get(f"/recordings/{recording_id}/audio").content == wav()


def test_idempotency_and_mismatch(client):
    recording_id = uuid4()
    assert upload(client, recording_id).status_code == 202
    assert upload(client, recording_id).status_code == 202
    other = bytearray(wav()); other[-1] = 1
    assert upload(client, recording_id, bytes(other)).status_code == 409
    assert len(client.get("/recordings").json()) == 1


def test_validation(client):
    assert upload(client, audio=b"not audio").status_code == 422
    assert client.post("/texts", json={"text": ""}).status_code == 422
    assert client.get("/recordings/not-uuid").status_code == 422
    assert client.get("/notes?q=\" OR *").status_code == 200


def test_retry_exhaustion_preserves_audio(client):
    class BrokenSTT:
        def transcribe(self, path):
            raise ProviderError("temporary_stt_failure")
    client.app.state.processor.stt = BrokenSTT()
    rid = upload(client).json()["id"]
    for _ in range(5):
        assert client.app.state.processor.tick()
    record = client.get(f"/recordings/{rid}").json()
    assert record["status"] == "failed" and record["attempts"] == 5
    assert record["has_audio"]
    assert not client.app.state.processor.tick()
    assert client.post(f"/process/{rid}").json()["attempts"] == 0


def test_permanent_error_no_retry(client):
    class BrokenSTT:
        def transcribe(self, path):
            raise ProviderError("api_key_missing", retryable=False)
    client.app.state.processor.stt = BrokenSTT()
    rid = upload(client).json()["id"]
    client.app.state.processor.tick()
    assert client.get(f"/recordings/{rid}").json()["status"] == "failed"
    assert not client.app.state.processor.tick()


def test_recovery_after_restart(settings):
    with TestClient(create_app(settings, worker=False)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        rid = upload(client).json()["id"]
        with client.app.state.sessions.begin() as session:
            session.get(Recording, rid).status = "processing"
    with TestClient(create_app(settings, worker=False)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        client.app.state.processor.recover()
        assert client.app.state.processor.tick()
        assert client.get(f"/recordings/{rid}").json()["status"] == "saved"


def test_edit_preserves_raw_and_reuses_note_path(client, settings):
    rid = upload(client).json()["id"]
    client.app.state.processor.tick()
    original = client.get(f"/recordings/{rid}").json()["raw_transcript"]
    assert client.patch(f"/recordings/{rid}/transcript", json={"text": "Моя правка"}).status_code == 202
    client.app.state.processor.tick()
    row = client.get(f"/recordings/{rid}").json()
    assert row["raw_transcript"] == original
    assert row["edited_transcript"] == "Моя правка"
    assert len(list(settings.notes_directory.rglob("*.md"))) == 1
    assert client.delete(f"/recordings/{rid}").status_code == 204
    assert client.get(f"/recordings/{rid}").status_code == 404
    assert not list(settings.notes_directory.rglob("*.md"))


def test_pending_mode_is_honest(settings):
    settings.llm_provider = "pending"
    settings.stt_provider = "local"
    with TestClient(create_app(settings, worker=False)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        rid = client.post("/texts", json={"text": "Наверное цена около 15 тысяч"}).json()["id"]
        client.app.state.processor.tick()
        row = client.get(f"/recordings/{rid}").json()
        assert row["status"] == "awaiting_ai"
        assert row["result"]["tasks"] == []
        assert row["result"]["clean_transcript"] == row["raw_transcript"]


def test_schema_and_hallucinated_evidence():
    with pytest.raises(ProviderError):
        validate_content('{"title":"invented"}', "test")
    value = verbatim_content("Может быть позвонить завтра").model_dump()
    value["tasks"] = [{"text": "Позвонить", "evidence": "Иван сказал", "deadline": None,
                       "deadline_evidence": None, "priority": "normal", "project": None, "status": "open"}]
    with pytest.raises(ProviderError, match="unsupported_task_evidence"):
        validate_content(value, "Может быть позвонить завтра")


def test_stt_checkpoint_survives_llm_failure(client):
    class CountingSTT:
        calls = 0
        def transcribe(self, path):
            self.calls += 1
            return "Настоящая расшифровка"
    class BrokenLLM:
        def process(self, *args):
            raise ProviderError("llm_timeout")
    stt = CountingSTT()
    client.app.state.processor.stt = stt
    client.app.state.processor.llm = BrokenLLM()
    rid = upload(client).json()["id"]
    client.app.state.processor.tick()
    client.app.state.processor.tick()
    assert stt.calls == 1
    assert client.get(f"/recordings/{rid}").json()["raw_transcript"] == "Настоящая расшифровка"


def test_backoff_and_processing_conflict(client):
    class Broken:
        def transcribe(self, path):
            raise ProviderError("timeout")
    client.app.state.processor.settings.retry_base_seconds = 10
    client.app.state.processor.stt = Broken()
    rid = upload(client).json()["id"]
    client.app.state.processor.tick()
    assert not client.app.state.processor.tick()
    with client.app.state.sessions.begin() as session:
        session.get(Recording, rid).status = "processing"
    assert client.delete(f"/recordings/{rid}").status_code == 409
    assert client.post(f"/process/{rid}").status_code == 409
