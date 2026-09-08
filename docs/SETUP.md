# Установка и сеть

## Windows

Python 3.12+ с Python Launcher (`py`), интернет на первую установку. `setup.bat` создаёт .venv, ставит backend и faster-whisper, генерирует случайный API_TOKEN только при отсутствии .env. Повторная установка не заменяет конфигурацию.

Модель Whisper small скачивается при первом распознавании в data/models. На этом компьютере модель подготовлена во время разработки. Последующая обработка локальна. Поддерживаемые зависимости зафиксированы в requirements.lock.txt; для воспроизведения:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe scripts\setup.py
```

`start.bat` запускает один сервер; `stop.bat` отправляет локальный запрос остановки. Не используйте uvicorn --workers > 1 для одной базы. Не переносите data на сетевую файловую систему.

## Домашняя сеть

Используйте адрес активного Wi-Fi/Ethernet из data/connection.txt. Сеть Windows должна быть частной; при системном запросе разрешите Python входящие подключения в частной сети. Автоматически firewall не отключается. Гостевой Wi-Fi часто запрещает соединение между устройствами.

Адрес ПК может измениться после перезагрузки роутера. В таком случае заново запустите start.bat, посмотрите connection.txt и обновите адрес в Android. Токен не меняется.

## Вне дома

Запись без доступа к ПК уже поддерживается: очередь остаётся на телефоне. Для обработки через мобильную сеть нужен включённый ПК и защищённый сетевой путь до него.

Практичный вариант — установить личный VPN на оба устройства (например, Tailscale), войти в один аккаунт и указать VPN-IP ПК `http://100.…:8765` в Android. Настройка аккаунта и реального подключения ещё не выполнена. Альтернатива для сервера — HTTPS reverse proxy; открывать текущий HTTP-порт прямо в интернет не следует. Пользовательские ключи и TLS-сертификаты в проект не включены.

## Автозапуск

При необходимости вручную выполните из папки проекта:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\enable-autostart.ps1
```

Отключить:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\disable-autostart.ps1
```

## Настройки

В .env: STT_PROVIDER local/openai/mock, LLM_PROVIDER pending/openai/mock, WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, LANGUAGE, TIMEZONE, DATA_DIRECTORY, NOTES_DIRECTORY, MAX_ATTEMPTS, RETRY_BASE_SECONDS, MAX_AUDIO_MB, SAVE_AUDIO, DELETE_AUDIO_AFTER_DAYS, LOG_LEVEL, HOST, PORT. После изменения — перезапуск.

SAVE_AUDIO=true и DELETE_AUDIO_AFTER_DAYS=0 сохраняют аудио без срока. Удаление по сроку применяется только к saved; ожидающие AI/ошибочные записи не очищаются. Настройка silence timeout находится в Android, потому что запись происходит на телефоне.

Скрипты запуска читают каталог данных и порт из .env. При изменении порта обновите адрес в Android и браузере. Путь к данным меняйте после остановки старого сервера; иначе старый процесс продолжит использовать прежний каталог.
