# REST API

Базовый адрес: `http://<адрес-ПК>:8765`. Защищённые запросы содержат `Authorization: Bearer <API_TOKEN>`. Схема доступна в `/openapi.json`, интерактивное описание — `/docs`.

| Метод и путь | Назначение |
|---|---|
| GET /health | Проверка процесса, без авторизации; не гарантирует готовность модели |
| POST /recordings | multipart: file, recording_id (UUID), captured_at (ISO с timezone), source, device |
| GET /recordings | Список; q, limit 1–100, offset |
| GET /recordings/{id} | Состояние, исходник, редакция, результат, SHA-256 |
| GET /recordings/{id}/audio | WAV, поддержка диапазонов FileResponse |
| GET /notes | Тот же список записей, включая ожидающие обработки |
| GET /notes/{id} | Та же детализация |
| GET /notes/{id}/markdown | Скачать готовый Markdown |
| POST /texts | JSON: text, необязательный captured_at; создаёт запись из текста |
| POST /process/{id} | Явный повтор; обнуляет попытки и AI-результат |
| PATCH /recordings/{id}/transcript | JSON: text; сохраняет редакцию и повторно ставит в очередь |
| DELETE /recordings/{id} | Удаляет файлы и запись на сервере |
| GET /settings/status | Имена провайдеров и признаки настройки, без секретов |

Аудио: WAV PCM 16 kHz, mono, 16 bit, 0.1–600 секунд. Максимум 24 МБ по умолчанию. Тело POST/PATCH должно иметь Content-Length. Устройство задаёт один UUID на одну запись и переиспользует при доставке. 202 подтверждает сохранённую загрузку; затем опрашивайте GET с ограниченной частотой и паузами.

Ошибки: 401 неверный токен, 404 отсутствует, 409 конфликт UUID либо запись сейчас обрабатывается, 411 отсутствует Content-Length, 413 размер, 422 формат или валидация. Ошибка AI/STT после успешной загрузки отражается в status/error, а не теряет принятый файл.

`processing_mode=pending` означает отсутствие AI; `mock` — тестовый результат. `saved` вместе с `mock` не является подтверждением реального AI. `awaiting_ai` означает, что дословный Markdown уже сохранён.

Для тестового WAV на этом ПК:

```powershell
.\.venv\Scripts\python.exe scripts\e2e.py C:\путь\к\записи.wav
```
