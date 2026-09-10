from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator


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

    @field_validator("deadline")
    @classmethod
    def iso_deadline(cls, value):
        if value is None:
            return value
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Deadline time requires timezone")
        return value


class MentionedDate(StrictModel):
    text: str
    resolved: str | None
    evidence: str
    uncertain: bool


class ActionIntent(StrictModel):
    kind: Literal['expense', 'income', 'debt_open', 'debt_payment', 'calendar']
    evidence: str = Field(min_length=1, max_length=4000)
    description: str = Field(min_length=1, max_length=500)
    amount_minor: int | None = Field(ge=1, le=100000000000)
    currency: Literal['KZT'] | None
    category: str | None = Field(max_length=80)
    person: str | None = Field(max_length=120)
    direction: Literal['i_owe', 'owed_to_me'] | None
    cash_moved: bool
    due_date: str | None = Field(pattern=r'^\d{4}-\d{2}-\d{2}$', description='Только срок долга YYYY-MM-DD, иначе null; для calendar всегда null')
    starts_at: AwareDatetime | None
    duration_minutes: int | None = Field(ge=1, le=1440)
    reminder_minutes: int | None = Field(ge=0, le=40320)
    clarification: str | None = Field(max_length=1000)

    @field_validator('due_date')
    @classmethod
    def valid_due_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


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
    actions: list[ActionIntent] = Field(default_factory=list, max_length=30)


class TextInput(StrictModel):
    text: str = Field(min_length=1, max_length=60000)
    captured_at: AwareDatetime | None = None


def verbatim_content(text: str) -> NoteContent:
    return NoteContent(title="Расшифровка — ожидает AI", summary="Конспект ещё не создан: подключите AI-провайдер.",
                       clean_transcript=text, important_points=[], tasks=[], people=[], companies=[], projects=[],
                       dates=[], ideas=[], decisions=[], questions=[], tags=[], category="thought", priority="normal",
                       confidence=0, uncertainties=["AI-обработка не выполнена."])
