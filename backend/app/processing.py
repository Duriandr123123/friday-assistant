import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, update, text
from sqlalchemy.orm import sessionmaker
from backend.app.db import Recording
from backend.app.schemas import NoteContent
from backend.app.providers.base import ProviderError
from backend.app.providers.stt import LocalWhisperProvider, CloudSTTProvider, MockSTTProvider
from backend.app.providers.llm import OpenAILLMProvider, PendingLLMProvider, MockLLMProvider
from backend.app.providers.notes import MarkdownNotesProvider

logger = logging.getLogger("jarvis")


class Processor:
    def __init__(self, settings, engine, stt=None, llm=None, notes=None):
        self.settings = settings
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        self.stt = stt or {"local": LocalWhisperProvider, "openai": CloudSTTProvider,
                           "mock": lambda s: MockSTTProvider()}[settings.stt_provider](settings)
        self.llm = llm or {"openai": OpenAILLMProvider, "pending": lambda s: PendingLLMProvider(),
                           "mock": lambda s: MockLLMProvider()}[settings.llm_provider](settings)
        self.notes = notes or MarkdownNotesProvider(settings)
        self.stop_event = threading.Event()
        self.thread = None
        self.mutex = threading.RLock()

    def recover(self):
        # The process-wide file lock ensures that no other server is still processing these rows.
        with self.sessions.begin() as session:
            session.execute(update(Recording).where(Recording.status == "processing")
                            .values(status="queued", next_attempt=0))

    def start(self):
        self.recover()
        self.thread = threading.Thread(target=self.run, name="jarvis-worker", daemon=True)
        self.thread.start()

    def run(self):
        next_cleanup = 0
        while not self.stop_event.is_set():
            try:
                if time.time() >= next_cleanup:
                    self.cleanup()
                    next_cleanup = time.time() + 3600
                did_work = self.tick()
            except Exception:
                logger.error("worker_iteration_failed")
                did_work = False
            if not did_work:
                self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def tick(self):
        with self.mutex:
            with self.sessions.begin() as session:
                row = session.scalar(select(Recording).where(Recording.status.in_(["queued", "retry"]),
                        Recording.next_attempt <= time.time()).order_by(Recording.created_at).limit(1))
                if row is None:
                    return False
                recording_id = row.id
                row.status = "processing"
                row.attempts += 1
            logger.info("processing_started", extra={"recording_id": recording_id})
        try:
            with self.sessions() as session:
                row = session.get(Recording, recording_id)
                if row.raw_transcript is None:
                    if not row.audio_path or not Path(row.audio_path).is_file():
                        raise ProviderError("audio_missing", retryable=False)
                    transcript = self.stt.transcribe(Path(row.audio_path)).strip()
                    if not transcript:
                        raise ProviderError("speech_not_detected", retryable=False)
                    if len(transcript) > 60000:
                        raise ProviderError("transcript_too_long", retryable=False)
                    row.raw_transcript = transcript
                    session.commit()
                    logger.info("transcribed", extra={"recording_id": recording_id})
                transcript = row.edited_transcript if row.edited_transcript is not None else row.raw_transcript
                if row.result is None:
                    content = self.llm.process(transcript, row.captured_at, self.settings.timezone)
                    row.result = content.model_dump(mode="json")
                    row.processing_mode = ("mock" if self.settings.stt_provider == "mock" or
                        self.settings.llm_provider == "mock" else self.settings.llm_provider)
                    session.commit()
                content = NoteContent.model_validate(row.result)
                path = self.notes.save(row, content)
                row.markdown_path = str(path)
                row.status = "awaiting_ai" if row.processing_mode == "pending" else "saved"
                row.error = None
                body = " ".join([row.raw_transcript or "", row.edited_transcript or "", content.model_dump_json()])
                session.execute(text("DELETE FROM notes_fts WHERE id=:id"), {"id": row.id})
                session.execute(text("INSERT INTO notes_fts (id,body) VALUES (:id,:body)"), {"id": row.id, "body": body})
                session.commit()
                # Retain audio by default. Cleanup only for successfully AI-processed notes.
                if not self.settings.save_audio and row.status == "saved" and row.audio_path:
                    Path(row.audio_path).unlink(missing_ok=True)
                logger.info(row.status, extra={"recording_id": recording_id})
        except Exception as exc:
            code = exc.code if isinstance(exc, ProviderError) else "processing_internal_error"
            retryable = exc.retryable if isinstance(exc, ProviderError) else True
            with self.sessions.begin() as session:
                row = session.get(Recording, recording_id)
                row.error = code
                row.status = "retry" if retryable and row.attempts < self.settings.max_attempts else "failed"
                row.next_attempt = time.time() + min(3600, self.settings.retry_base_seconds * 2 ** (row.attempts - 1))
            logger.warning(code, extra={"recording_id": recording_id})
        return True

    def cleanup(self):
        days = self.settings.delete_audio_after_days
        if days <= 0:
            return
        with self.sessions() as session:
            for row in session.scalars(select(Recording).where(Recording.status == "saved")):
                if (datetime.now(timezone.utc) - datetime.fromisoformat(row.created_at)).total_seconds() > days * 86400:
                    if row.audio_path:
                        Path(row.audio_path).unlink(missing_ok=True)
