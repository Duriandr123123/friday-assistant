from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from sqlalchemy.orm import sessionmaker
from backend.app.core.config import Settings
from backend.app.core.logging import configure
from backend.app.db import make_engine, migrate
from backend.app.processing import Processor
from backend.app.api import router


def create_app(settings=None, *, worker=True, stt=None, llm=None, notes=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        lock = FileLock(str(settings.data_directory / "server.lock"), timeout=0)
        lock.acquire()
        engine = make_engine(settings.data_directory)
        try:
            migrate(engine)
            configure(settings)
            app.state.settings = settings
            app.state.sessions = sessionmaker(engine, expire_on_commit=False)
            app.state.processor = Processor(settings, engine, stt=stt, llm=llm, notes=notes)
            if worker:
                app.state.processor.start()
            yield
        finally:
            if hasattr(app.state, "processor"):
                app.state.processor.stop()
            engine.dispose()
            lock.release()

    app = FastAPI(title="Джарвис — заметки", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    import threading
    from backend.app.onboarding import router as pairing_router
    app.state.pair_code=None
    app.state.pair_lock=threading.Lock()
    app.include_router(pairing_router)

    @app.middleware("http")
    async def security_headers(request, call_next):
        # WAV uploads must declare their size, so multipart parsing cannot spool an unbounded body.
        maximum = (256 if request.url.path == '/imports/audio' else settings.max_audio_mb) * 1024 * 1024 + 65536
        length = request.headers.get("content-length", "0")
        if request.method in ("POST", "PATCH") and "content-length" not in request.headers:
            return JSONResponse({"detail": "Требуется Content-Length"}, status_code=411)
        if not length.isdigit() or int(length) > maximum:
            return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path not in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "jarvis-thoughts", "version": "0.1.0"}

    static = Path(__file__).parent / "web"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")
        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static / "index.html")
    return app


app = create_app()
