from pathlib import Path
import httpx
from backend.app.providers.base import ProviderError


class LocalWhisperProvider:
    def __init__(self, settings):
        self.settings = settings
        self.model = None

    def transcribe(self, path: Path) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ProviderError("local_stt_not_installed", retryable=False)
        if self.model is None:
            self.model = WhisperModel(self.settings.whisper_model, device=self.settings.whisper_device,
                                      compute_type=self.settings.whisper_compute_type,
                                      download_root=str(self.settings.data_directory / "models"))
        segments, info = self.model.transcribe(str(path), language=self.settings.language,
            vad_filter=True, beam_size=5, initial_prompt="Roll.Mart, Kaspi, Meta Ads, Codex, WhatsApp, тенге, роллшторы.")
        return " ".join(s.text.strip() for s in segments).strip()


class CloudSTTProvider:
    def __init__(self, settings):
        self.settings = settings

    def transcribe(self, path: Path) -> str:
        from .llm import request_json
        with path.open("rb") as audio:
            data = request_json(self.settings, "audio/transcriptions", files={"file": (path.name, audio)},
                data={"model": self.settings.openai_stt_model, "language": self.settings.language,
                      "prompt": "Roll.Mart, Kaspi, Meta Ads, Codex, WhatsApp, тенге, роллшторы."})
        return data["text"]


class MockSTTProvider:
    def transcribe(self, path: Path) -> str:
        return "ТЕСТОВАЯ ЗАПИСЬ. Надо завтра позвонить поставщику роллштор до двенадцати. Возможно цена около 15 тысяч."
