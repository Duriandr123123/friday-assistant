from datetime import datetime
from zoneinfo import ZoneInfo
import re
import hashlib
import json
from pathlib import Path
from backend.app.storage import atomic_write


def escape(text):
    return str(text).replace("<", "&lt;").replace(">", "&gt;")


def entity_name(value):
    clean = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', ' ', value)
    return ' '.join(clean.split()).strip(' .')[:100] or 'Без названия'


def actual_people(values, transcript):
    excluded = {'сюзанна','сузанна','сюзана','пятница','джарвис','чат gpt','chatgpt','партнеры','партнёры'}
    result = []
    for value in values:
        name = ' '.join(value.split())
        if name.casefold() in excluded or not re.fullmatch(r'[А-ЯЁA-Z][а-яёa-z]+(?:[ -][А-ЯЁA-Z][а-яёa-z]+){0,2}',name): continue
        # Conservative evidence: a named person in a human interaction, not a lone word or subtitle credit.
        context = re.search(r'(?:с|для|от|к|позвони(?:ть)?|напиши|написать|должен|должна|должны|зовут|встретиться|встретился)\s+'+re.escape(name)+r'\b',transcript,re.I)
        if context and name.casefold() not in [n.casefold() for n in result]: result.append(name)
    return result


class MarkdownNotesProvider:
    def __init__(self, settings):
        self.settings = settings

    def link(self, path, label):
        root = self.settings.notes_directory
        vault = next((p for p in [root, *root.parents] if (p / '.obsidian').is_dir()), root)
        relative = path.relative_to(vault).with_suffix('').as_posix()
        label = re.sub(r'[\[\]|\r\n]', ' ', label)
        return f'[[{relative}|{label}]]'

    def save(self, recording, content):
        dt = datetime.fromisoformat(recording.captured_at).astimezone(ZoneInfo(self.settings.timezone))
        # Stable UUID path survives title edits and retries without duplicate notes.
        folder = self.settings.notes_directory / 'Заметки' / dt.strftime('%Y-%m')
        base = f"{dt:%d.%m %H-%M} — {entity_name(content.title)}"
        path = folder / (base + '.md')
        index = 2
        while path.exists() and ('recording_id: ' + json.dumps(recording.id)) not in path.read_text(encoding='utf-8'):
            path = folder / (base + f' ({index}).md'); index += 1
        existing = getattr(recording, 'markdown_path', None)
        if existing and Path(existing).is_relative_to(self.settings.notes_directory/'Заметки'):
            path = Path(existing)
        people = actual_people(content.people, recording.edited_transcript or recording.raw_transcript or '')
        lines = ['---', 'recording_id: ' + json.dumps(recording.id),
                 'created: ' + json.dumps(dt.isoformat()), 'category: ' + content.category,
                 'tags: ' + json.dumps(list(dict.fromkeys(['сюзанна', content.category] + [re.sub(r'[^\w/-]', '_',t) for t in content.tags])), ensure_ascii=False),
                 '---', f"# {escape(content.title)}", "", f"Записано: {dt.isoformat()}",
                 f"Источник: {escape(recording.source)}", f"Режим обработки: {recording.processing_mode}",
                 f"Категория: {content.category} · Приоритет: {content.priority}", "", "## Кратко", escape(content.summary)]
        day = self.settings.notes_directory / 'Дни' / f'{dt:%Y-%m-%d}.md'
        if not day.exists():
            atomic_write(day, (f'# {dt:%d.%m.%Y}\n\nЗаписи дня доступны через обратные ссылки Obsidian.\n').encode('utf-8'))
        links = [self.link(day, f'{dt:%d.%m.%Y}')]
        groups = [('Люди', people), ('Проекты', content.projects),
                  ('Компании', content.companies)]
        for group, values in groups:
            for value in dict.fromkeys(values):
                name = entity_name(value)
                hub = self.settings.notes_directory / 'Связи' / group / (name + '.md')
                suffix = 2
                while hub.exists() and hub.read_text(encoding='utf-8').splitlines()[0].casefold() != ('# '+escape(value)).casefold():
                    # User-authored pages with the same title remain untouched.
                    if 'Связанные записи доступны' not in hub.read_text(encoding='utf-8'): break
                    hub = self.settings.notes_directory/'Связи'/group/(name+f' ({suffix}).md'); suffix += 1
                if not hub.exists():
                    atomic_write(hub, (f'# {escape(value)}\n\nСвязанные записи доступны в панели «Обратные ссылки» Obsidian.\n'
                        'Эту страницу можно дополнять своими заметками.\n').encode('utf-8'))
                links.append(self.link(hub, value))
        if content.category == 'finance' or any(a.kind != 'calendar' for a in content.actions):
            links.append(self.link(self.settings.notes_directory / 'Финансы' / 'Бюджет.md', 'Бюджет'))
        if any(a.kind.startswith('debt') for a in content.actions):
            links.append(self.link(self.settings.notes_directory / 'Финансы' / 'Долги.md', 'Долги'))
        if links:
            lines += ['', '## Связи', ' · '.join(links)]
        sections = [("Главное", content.important_points), ("Люди", people), ("Компании", content.companies),
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
