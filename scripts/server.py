"""Single-instance server; stop is a local sentinel, never an unauthenticated network endpoint."""
import os
import sys
import threading
from pathlib import Path
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.core.config import Settings


def main():
    settings = Settings()
    settings.prepare()
    stop = settings.data_directory / "stop.request"
    pid = settings.data_directory / "server.pid"
    stop.unlink(missing_ok=True)
    server = uvicorn.Server(uvicorn.Config("backend.app.main:app", host=settings.host, port=settings.port,
                                           access_log=False, log_level="warning"))
    done = threading.Event()
    def watch():
        while not done.wait(1):
            if stop.exists():
                server.should_exit = True
                break
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        pid.write_text(str(os.getpid()), encoding="ascii")
        server.run()
    finally:
        done.set()
        pid.unlink(missing_ok=True)
        stop.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
