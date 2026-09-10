from types import SimpleNamespace
from backend.app.providers.notes import MarkdownNotesProvider, entity_name
from backend.app.schemas import verbatim_content


def test_links_are_safe_stable_and_hubs_preserve_user_notes(tmp_path):
    (tmp_path / '.obsidian').mkdir()
    root = tmp_path / 'Сюзанна'
    provider = MarkdownNotesProvider(SimpleNamespace(notes_directory=root, timezone='Asia/Qyzylorda'))
    row = SimpleNamespace(id='test-record', captured_at='2026-09-10T10:00:00+05:00',
        source='android', processing_mode='pending', raw_transcript='Встретился с Алексей', edited_transcript=None)
    content = verbatim_content('Пример')
    content.people = ['Алексей', '../../опасный|текст']
    first = provider.save(row, content)
    hub = root / 'Связи' / 'Люди' / (entity_name('Алексей') + '.md')
    hub.write_text('Мои дополнения', encoding='utf-8')
    content.people = ['Алексей']
    assert provider.save(row, content) == first
    assert hub.read_text(encoding='utf-8') == 'Мои дополнения'
    assert '[[Сюзанна/Связи/Люди/' in first.read_text(encoding='utf-8')
    assert len(list(root.glob('Заметки/*/*.md'))) == 1
    assert all(p.resolve().is_relative_to(root.resolve()) for p in root.rglob('*.md'))


def test_people_excludes_tools_roles_and_isolated_words():
    from backend.app.providers.notes import actual_people
    assert actual_people(['ChatGPT','Сюзанна','партнёры','Бойково'], 'Бойково') == []
    assert actual_people(['Алексей'], 'Встреча с Алексей завтра') == ['Алексей']
