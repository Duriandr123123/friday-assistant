from pathlib import Path
from typing import Protocol
from backend.app.schemas import NoteContent


class ProviderError(Exception):
    def __init__(self, code: str, retryable=True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class SpeechToTextProvider(Protocol):
    def transcribe(self, path: Path) -> str: ...


class LLMProvider(Protocol):
    def process(self, text: str, captured_at: str, timezone: str) -> NoteContent: ...


class NotesProvider(Protocol):
    def save(self, recording, content: NoteContent) -> Path: ...
