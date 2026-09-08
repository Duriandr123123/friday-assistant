from datetime import datetime
from zoneinfo import ZoneInfo
import re
from backend.app.storage import atomic_write


def escape(text):
    return str(text).replace("<", "&lt;").replace(">", "&gt;")


class MarkdownNotesProvider:
    def __init__(self, settings):
        self.settings = settings

    def save(self, recording, content):
        dt = datetime.fromisoformat(recording.captured_at).astimezone(ZoneInfo(self.settings.timezone))
        # Stable UUID path survives title edits and retries without duplicate notes.
        path = self.settings.notes_directory / dt.strftime("%Y/%m/%d") / f"{dt:%Y-%m-%d_%H-%M}_{recording.id}.md"
        lines = [f"# {escape(content.title)}", "", f"Записано: {dt.isoformat()}",
                 f"ID: {recording.id}", f"Режим обработки: {recording.processing_mode}",
                 f"Категория: {content.category} · Приоритет: {content.priority}", "", "## Кратко", escape(content.summary)]
        sections = [("Главное", content.important_points), ("Люди", content.people), ("Компании", content.companies),
                    ("Проекты", content.projects), ("Идеи", content.ideas), ("Решения", content.decisions),
                    ("Вопросы", content.questions), ("Неопределённость", content.uncertainties), ("Теги", content.tags)]
        lines += ["", "## Задачи"]
        for task in content.tasks:
            lines += [f"- [{'x' if task.status == 'done' else ' '}] {escape(task.text)}" +
                      (f" — срок: {escape(task.deadline)}" if task.deadline else ""),
                      f"  - Основание: {escape(task.evidence)}"]
        if not content.tasks:
            lines += ["Задачи не выделены."]
        for title, values in sections:
            if values:
                lines += ["", f"## {title}"] + [f"- {escape(v)}" for v in values]
        if content.dates:
            lines += ["", "## Даты"] + [f"- {escape(d.text)} → {escape(d.resolved or 'не уточнено')}" +
                         (" (неуверенно)" if d.uncertain else "") for d in content.dates]
        lines += ["", "## Исправленный текст", escape(content.clean_transcript),
                  "", "## Исходная расшифровка", escape(recording.raw_transcript or "")]
        if recording.edited_transcript is not None:
            lines += ["", "## Редакция пользователя", escape(recording.edited_transcript)]
        atomic_write(path, ("\n".join(lines) + "\n").encode("utf-8"))
        return path
