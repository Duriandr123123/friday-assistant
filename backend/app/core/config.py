from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import os
ROOT = Path(os.environ.get("FRIDAY_HOME", str(Path(__file__).resolve().parents[3])))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    assistant_name: str = "Джарвис"
    api_token: SecretStr = SecretStr("")
    host: str = "0.0.0.0"
    port: int = 8765
    timezone: str = "Asia/Qyzylorda"
    language: str = "ru"
    data_directory: Path = ROOT / "data"
    notes_directory: Path = ROOT / "notes"
    stt_provider: Literal["local", "openai", "mock"] = "local"
    llm_provider: Literal["pending", "openai", "mock"] = "pending"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_stt_model: str = "whisper-1"
    openai_llm_model: str = ""
    max_attempts: int = Field(5, ge=1, le=20)
    retry_base_seconds: float = Field(10, ge=0, le=3600)
    max_audio_mb: int = Field(24, ge=1, le=100)
    save_audio: bool = True
    delete_audio_after_days: int = Field(0, ge=0)
    log_level: str = "INFO"

    @field_validator("data_directory", "notes_directory")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        return value.resolve() if value.is_absolute() else (ROOT / value).resolve()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    def prepare(self):
        token = self.api_token.get_secret_value()
        if len(token) < 24 or token == "REPLACE_WITH_RANDOM_TOKEN":
            raise ValueError("Задайте API_TOKEN длиной не менее 24 символов; запустите setup.bat")
        for path in (self.data_directory, self.data_directory / "audio", self.notes_directory):
            path.mkdir(parents=True, exist_ok=True)
