from pathlib import Path
from sqlalchemy import create_engine, event, String, Text, Integer, Float, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(50))
    captured_at: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(80), default="android")
    device: Mapped[str] = mapped_column(String(120), default="unknown")
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    markdown_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_mode: Mapped[str] = mapped_column(String(32), default="pending")


def make_engine(directory: Path):
    engine = create_engine(f"sqlite:///{(directory / 'jarvis.sqlite3').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 30})
    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
    return engine


def migrate(engine):
    from alembic.config import Config
    from alembic import command
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
