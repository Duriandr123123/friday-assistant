import hashlib
import io
import hmac
import json
import logging
import os
import re
import tempfile
import wave
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from backend.app.db import Recording, Action, Preference
from backend.app.schemas import TextInput

security = HTTPBearer(auto_error=False)
logger = logging.getLogger("jarvis")


def authorize(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
    expected = request.app.state.settings.api_token.get_secret_value()
    if not credentials or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(401, "Неверный токен", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(dependencies=[Depends(authorize)])


@router.post("/imports/audio", status_code=202)
def import_audio(request: Request, file: Annotated[UploadFile, File()],
                 captured_at: Annotated[str, Form()]):
    from backend.app.import_audio import normalize_audio
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Укажите дату с часовым поясом")
    try:
        file.file.seek(0, 2)
        if file.file.tell() > 256 * 1024 * 1024:
            raise HTTPException(413, "Максимальный размер файла — 256 МБ")
        file.file.seek(0)
        original_hash = hashlib.file_digest(file.file, "sha256").hexdigest()
        file.file.seek(0)
        try:
            parts = list(normalize_audio(file.file))
        except Exception as exc:
            raise HTTPException(422, "Не удалось прочитать аудио. Нужен WAV, MP3, M4A или OGG длительностью до 60 минут.") from exc
        rows = []
        for index, (offset, content) in enumerate(parts):
            rid = uuid5(NAMESPACE_URL, f"jarvis-recorder-v1:{original_hash}:{index}")
            rows.append(upload(request, UploadFile(file=io.BytesIO(content), filename="import.wav"),
                rid, (captured + timedelta(seconds=offset)).isoformat(),
                source="recorder-import", device=(file.filename or "Диктофон")[:120]))
        return {"recordings": rows}
    finally:
        file.file.close()


def view(row):
    return {"id": row.id, "created_at": row.created_at, "captured_at": row.captured_at,
            "source": row.source, "device": row.device, "status": row.status,
            "attempts": row.attempts, "next_attempt": row.next_attempt, "error": row.error,
            "raw_transcript": row.raw_transcript, "edited_transcript": row.edited_transcript,
            "result": row.result, "processing_mode": row.processing_mode,
            "has_audio": bool(row.audio_path and Path(row.audio_path).is_file()),
            "has_markdown": bool(row.markdown_path and Path(row.markdown_path).is_file()),
            "sha256": row.sha256}


def get_row(session, recording_id):
    row = session.get(Recording, str(recording_id))
    if not row:
        raise HTTPException(404, "Запись не найдена")
    return row


@router.post("/recordings", status_code=202)
def upload(request: Request, file: Annotated[UploadFile, File()],
           recording_id: Annotated[UUID, Form()], captured_at: Annotated[str, Form()],
           source: Annotated[str, Form(max_length=80)] = "android",
           device: Annotated[str, Form(max_length=120)] = "unknown"):
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "captured_at должен содержать дату, время и часовой пояс")
    settings = request.app.state.settings
    # WAV PCM is the device interchange format: recoverable after an interrupted recording.
    folder = settings.data_directory / "audio"
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix="upload-", suffix=".tmp", dir=folder)
        sha = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := file.file.read(65536):
                size += len(chunk)
                if size > settings.max_audio_mb * 1024 * 1024:
                    raise HTTPException(413, "Аудиофайл слишком большой")
                out.write(chunk)
                sha.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        try:
            with wave.open(temporary, "rb") as audio:
                if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or audio.getframerate() != 16000:
                    raise ValueError()
                frames = audio.getnframes()
                if not 1600 <= frames <= 16000 * 600 or len(audio.readframes(frames)) != frames * 2:
                    raise ValueError()
        except (wave.Error, EOFError, ValueError):
            raise HTTPException(422, "Нужен WAV PCM: 16 кГц, mono, 16 bit, 0.1–600 секунд")
        digest = sha.hexdigest()
        with request.app.state.processor.mutex, request.app.state.sessions.begin() as session:
            existing = session.get(Recording, str(recording_id))
            if existing:
                if existing.sha256 != digest:
                    raise HTTPException(409, "Этот UUID уже связан с другим аудио")
                return view(existing)
            destination = folder / f"{recording_id}.wav"
            os.replace(temporary, destination)
            row = Recording(id=str(recording_id), created_at=datetime.now(timezone.utc).isoformat(),
                            captured_at=captured.isoformat(), source=source, device=device,
                            audio_path=str(destination), sha256=digest, status="queued")
            session.add(row)
            session.flush()
            result = view(row)
        logger.info("uploaded", extra={"recording_id": str(recording_id)})
        return result
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        file.file.close()


@router.post("/texts", status_code=202)
def create_text(payload: TextInput, request: Request):
    now = datetime.now(timezone.utc)
    with request.app.state.sessions.begin() as session:
        row = Recording(id=str(uuid4()), created_at=now.isoformat(),
            captured_at=(payload.captured_at or now).isoformat(), source="text", device="web",
            raw_transcript=payload.text, sha256=hashlib.sha256(payload.text.encode()).hexdigest(), status="queued")
        session.add(row)
        session.flush()
        return view(row)


@router.get("/recordings")
@router.get("/notes")
def list_recordings(request: Request, q: str = Query("", max_length=300),
                    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with request.app.state.sessions() as session:
        statement = select(Recording)
        if q.strip():
            tokens = re.findall(r"\w+", q, flags=re.UNICODE)
            if not tokens:
                return []
            query = " AND ".join('"' + token + '"*' for token in tokens)
            ids = session.execute(text("SELECT id FROM notes_fts WHERE notes_fts MATCH :query"), {"query": query}).scalars().all()
            statement = statement.where(Recording.id.in_(ids))
        return [view(row) for row in session.scalars(statement.order_by(Recording.created_at.desc()).offset(offset).limit(limit))]


@router.get("/recordings/{recording_id}")
@router.get("/notes/{recording_id}")
def detail(recording_id: UUID, request: Request):
    with request.app.state.sessions() as session:
        result = view(get_row(session, recording_id))
        result['action_results'] = [{'id':a.id,'description':a.payload['description'],'kind':a.payload['kind'],
            'status':a.status,'amount_minor':a.payload.get('amount_minor'),'error':a.error}
            for a in session.scalars(select(Action).where(Action.recording_id==str(recording_id)))]
        return result


@router.get("/recordings/{recording_id}/audio")
def audio(recording_id: UUID, request: Request):
    with request.app.state.sessions() as session:
        row = get_row(session, recording_id)
        if not row.audio_path or not Path(row.audio_path).is_file():
            raise HTTPException(404, "Аудио отсутствует")
        return FileResponse(row.audio_path, media_type="audio/wav")


@router.get("/notes/{recording_id}/markdown")
def markdown(recording_id: UUID, request: Request):
    with request.app.state.sessions() as session:
        row = get_row(session, recording_id)
        if not row.markdown_path or not Path(row.markdown_path).is_file():
            raise HTTPException(404, "Заметка ещё не создана")
        return FileResponse(row.markdown_path, media_type="text/markdown", filename=Path(row.markdown_path).name)


@router.post("/process/{recording_id}", status_code=202)
def retry(recording_id: UUID, request: Request):
    with request.app.state.processor.mutex, request.app.state.sessions.begin() as session:
        row = get_row(session, recording_id)
        if row.status == "processing":
            raise HTTPException(409, "Запись уже обрабатывается")
        row.status, row.error, row.next_attempt, row.attempts = "queued", None, 0, 0
        row.result = None
        return view(row)


@router.patch("/recordings/{recording_id}/transcript", status_code=202)
def edit(recording_id: UUID, payload: TextInput, request: Request):
    with request.app.state.processor.mutex, request.app.state.sessions.begin() as session:
        row = get_row(session, recording_id)
        if row.status == "processing":
            raise HTTPException(409, "Дождитесь окончания обработки")
        row.edited_transcript = payload.text
        # Explicit manual transcription can rescue an STT failure without fabricating a raw STT result.
        if row.raw_transcript is None:
            row.raw_transcript = ""
        row.result = None
        row.status, row.error, row.next_attempt, row.attempts = "queued", None, 0, 0
        return view(row)


@router.delete("/recordings/{recording_id}", status_code=204)
def delete(recording_id: UUID, request: Request):
    with request.app.state.processor.mutex, request.app.state.sessions.begin() as session:
        row = get_row(session, recording_id)
        if row.status == "processing":
            raise HTTPException(409, "Дождитесь окончания обработки")
        if session.scalar(select(Action).where(Action.recording_id == row.id, Action.status != 'cancelled').limit(1)):
            raise HTTPException(409, 'Сначала отмените действия, связанные с записью, в разделе «Финансы и поручения»')
        for path in (row.audio_path, row.markdown_path):
            if path:
                Path(path).unlink(missing_ok=True)
        session.execute(text("DELETE FROM notes_fts WHERE id=:id"), {"id": row.id})
        session.delete(row)


@router.get("/settings/status")
def settings_status(request: Request):
    s = request.app.state.settings
    return {"assistant_name": s.assistant_name, "stt_provider": s.stt_provider,
            "llm_provider": s.llm_provider, "timezone": s.timezone,
            "api_key_configured": bool(s.openai_api_key.get_secret_value()),
            "llm_model_configured": bool(s.openai_llm_model)}


@router.get('/actions')
def action_status(request: Request):
    from backend.app.actions import snapshot
    with request.app.state.sessions() as session:
        result = snapshot(session)
    result['calendar'] = request.app.state.processor.calendar.status()
    return result


@router.put('/budget')
def set_budget(request: Request, payload: dict):
    amount = payload.get('initial_minor')
    if type(amount) is not int or not 0 <= amount <= 100000000000:
        raise HTTPException(422, 'Нужна неотрицательная сумма в тиынах')
    processor = request.app.state.processor
    with processor.mutex, request.app.state.sessions.begin() as session:
        pref = session.get(Preference, 'budget')
        if pref: pref.value = {'initial_minor':amount}
        else: session.add(Preference(key='budget', value={'initial_minor':amount}))
    processor.actions.run_pending()
    return action_status(request)


@router.post('/actions/{action_id}/cancel')
def cancel_action(action_id: UUID, request: Request):
    try: request.app.state.processor.actions.cancel(str(action_id))
    except Exception as exc:
        raise HTTPException(409, str(exc) if isinstance(exc,ValueError) else 'Не удалось отменить действие. Попробуйте после подключения календаря.')
    return action_status(request)


@router.put('/actions/{action_id}')
def clarify_action(action_id: UUID, request: Request, payload: dict):
    from backend.app.schemas import ActionIntent
    from pydantic import ValidationError
    try: intent = ActionIntent.model_validate(payload)
    except ValidationError: raise HTTPException(422, 'Проверьте поля поручения')
    processor = request.app.state.processor
    with processor.mutex, request.app.state.sessions.begin() as session:
        row = session.get(Action,str(action_id))
        if not row: raise HTTPException(404,'Действие не найдено')
        if row.status in ('applied','cancelled'):
            raise HTTPException(409,'Выполненное действие сначала отмените; для новой операции создайте новую запись')
        if row.payload['kind'] == 'calendar' and row.result.get('calendar_attempted'):
            raise HTTPException(409,'Сначала отмените ожидающую встречу: она могла сохраниться в Google до обрыва связи')
        row.payload, row.status, row.error = intent.model_dump(mode='json'), 'pending', None
    processor.actions.run_pending()
    return action_status(request)


@router.post('/actions/retry')
def retry_actions(request: Request):
    request.app.state.processor.actions.run_pending()
    return action_status(request)


@router.post('/calendar/client')
def calendar_client(request: Request, payload: dict):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Подключите календарь в браузере на самом ПК')
    try: request.app.state.processor.calendar.configure(payload)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return request.app.state.processor.calendar.status()


@router.post('/calendar/connect')
def calendar_connect(request: Request):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Откройте панель на самом компьютере')
    try: url = request.app.state.processor.calendar.begin()
    except Exception: raise HTTPException(409,'Сначала загрузите OAuth JSON Google Desktop app или дождитесь окончания текущего входа')
    return {'url':url}
