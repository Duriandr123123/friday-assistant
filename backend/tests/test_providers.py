import pytest
import httpx
from datetime import datetime
from backend.app.providers.llm import OpenAILLMProvider, request_json, validate_content
from backend.app.providers.base import ProviderError
from backend.app.schemas import verbatim_content
from test_system import settings, client, upload


def test_notes_failure_reuses_ai_checkpoint(client):
    processor = client.app.state.processor
    original_notes = processor.notes
    original_llm = processor.llm
    class CountingLLM:
        calls = 0
        def process(self, *args):
            self.calls += 1
            return original_llm.process(*args)
    class BrokenNotes:
        def save(self, *args):
            raise OSError("disk temporarily unavailable")
    llm = CountingLLM()
    processor.llm = llm
    processor.notes = BrokenNotes()
    rid = upload(client).json()["id"]
    processor.tick()
    assert client.get(f"/recordings/{rid}").json()["status"] == "retry"
    processor.notes = original_notes
    processor.tick()
    assert llm.calls == 1
    assert client.get(f"/recordings/{rid}").json()["status"] == "saved"


def test_cloud_request_schema_and_capture_time(settings, monkeypatch):
    settings.openai_llm_model = "test-model"
    captured = "2026-09-08T23:35:00+05:00"
    content = verbatim_content("Наверное цена около 15 тысяч")
    seen = {}
    def fake(settings, endpoint, **kwargs):
        seen.update(kwargs["json"])
        assert endpoint == "responses"
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": content.model_dump_json()}]}]}
    monkeypatch.setattr("backend.app.providers.llm.request_json", fake)
    result = OpenAILLMProvider(settings).process(content.clean_transcript, captured, "Asia/Qyzylorda")
    assert result.clean_transcript == content.clean_transcript
    assert captured in seen["input"]
    assert seen["store"] is False
    assert seen["text"]["format"]["strict"] is True


def test_missing_key_not_retried(settings):
    with pytest.raises(ProviderError) as exc:
        request_json(settings, "responses", json={})
    assert exc.value.code == "api_key_missing"
    assert not exc.value.retryable


@pytest.mark.parametrize("status,retryable", [(401, False), (429, True), (500, True), (400, False)])
def test_provider_http_failures_sanitized(settings, monkeypatch, status, retryable):
    from pydantic import SecretStr
    settings.openai_api_key = SecretStr("private-value-must-not-escape")
    transport = httpx.MockTransport(lambda req: httpx.Response(status, text="private-value-must-not-escape"))
    original = httpx.Client
    monkeypatch.setattr("backend.app.providers.llm.httpx.Client", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(ProviderError) as exc:
        request_json(settings, "responses", json={})
    assert exc.value.retryable == retryable
    assert "private-value" not in str(exc.value)


def test_invalid_and_unjustified_deadline():
    content = verbatim_content("Позвонить завтра").model_dump()
    task = {"text": "Позвонить", "evidence": "Позвонить завтра", "deadline": "2026-09-09T12:00:00",
            "deadline_evidence": "завтра", "priority": "normal", "project": None, "status": "open"}
    content["tasks"] = [task]
    with pytest.raises(ProviderError, match="invalid_ai_schema"):
        validate_content(content, "Позвонить завтра")
    task["deadline"] = "2026-09-09"
    task["deadline_evidence"] = None
    with pytest.raises(ProviderError, match="unsupported_deadline"):
        validate_content(content, "Позвонить завтра")


def test_truncated_wav_rejected(client):
    from test_system import wav
    assert upload(client, audio=wav()[:-100]).status_code == 422


def test_limits_and_filename_escape(client):
    assert client.post("/texts", json={"text": "x" * 60001}).status_code == 422
    assert client.get("/notes?limit=101").status_code == 422
    rid = client.post("/texts", json={"text": "<script>alert(1)</script>"}).json()["id"]
    client.app.state.processor.tick()
    assert "<script>" not in client.get(f"/notes/{rid}/markdown").text
