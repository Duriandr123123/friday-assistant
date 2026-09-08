from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Task(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000)
    deadline: str | None
    deadline_evidence: str | None
    priority: Literal["low", "normal", "high"]
    project: str | None
    status: Literal["open", "done", "cancelled"]


class MentionedDate(StrictModel):
    text: str
    resolved: str | None
    evidence: str
    uncertain: bool


class NoteContent(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(max_length=6000)
    clean_transcript: str = Field(max_length=60000)
    important_points: list[str]
    tasks: list[Task]
    people: list[str]
    companies: list[str]
    projects: list[str]
    dates: list[MentionedDate]
    ideas: list[str]
    decisions: list[str]
    questions: list[str]
    tags: list[str]
    category: Literal["thought", "idea", "task", "purchase", "reminder", "business", "personal", "decision", "question", "contact", "finance", "mixed"]
    priority: Literal["low", "normal", "high"]
    confidence: float = Field(ge=0, le=1)
    uncertainties: list[str]


class TextInput(StrictModel):
    text: str = Field(min_length=1, max_length=60000)
    captured_at: AwareDatetime | None = None


def verbatim_content(text: str) -> NoteContent:
    return NoteContent(title="Расшифровка — ожидает AI", summary="Конспект ещё не создан: подключите AI-провайдер.",
                       clean_transcript=text, important_points=[], tasks=[], people=[], companies=[], projects=[],
                       dates=[], ideas=[], decisions=[], questions=[], tags=[], category="thought", priority="normal",
                       confidence=0, uncertainties=["AI-обработка не выполнена."])
