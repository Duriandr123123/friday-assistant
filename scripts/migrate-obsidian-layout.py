"""One-time layout migration; run with the server stopped. Back up before any writes."""
import json
import re
import shutil
import sqlite3
import time
import threading
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from backend.app.core.config import Settings
from backend.app.db import make_engine, Recording
from backend.app.providers.notes import MarkdownNotesProvider, entity_name, actual_people
from backend.app.schemas import NoteContent
from backend.app.actions import ActionService

s = Settings()
root = s.notes_directory
vault = root.parent
backup = s.data_directory/'backups'/('obsidian-layout-'+str(int(time.time())))
backup.mkdir(parents=True)
shutil.copytree(root, backup/'vault')
with sqlite3.connect(s.data_directory/'jarvis.sqlite3') as c, sqlite3.connect(backup/'jarvis.sqlite3') as b:
    c.backup(b)
sessions = sessionmaker(make_engine(s.data_directory), expire_on_commit=False)
provider = MarkdownNotesProvider(s)
mapping = {}
def key(p): return p.relative_to(vault).with_suffix('').as_posix()
def remove_backed_up(p):
    assert p.resolve().is_relative_to(root.resolve())
    assert (backup/'vault'/p.relative_to(root)).is_file()
    p.unlink()

with sessions.begin() as session:
    for r in session.scalars(select(Recording)):
        if not r.result: continue
        old = Path(r.markdown_path) if r.markdown_path else None
        new = provider.save(r, NoteContent.model_validate(r.result))
        r.markdown_path = str(new)
        if old and old != new and old.is_file():
            mapping[key(old)] = key(new)
            remove_backed_up(old)

# Archived notes no longer in the application database retain their original content.
for p in list(root.glob('????/??/??/*.md')):
    content = p.read_text(encoding='utf-8')
    title = re.search(r'^# (.+)$',content,re.M)
    base = p.name[:16].replace('_',' ')+' — '+entity_name(title[1] if title else 'Заметка')
    new = root/'Заметки'/p.parent.parent.parent.name/p.parent.parent.name/(base+'.md')
    new.parent.mkdir(parents=True,exist_ok=True)
    n=2
    while new.exists():
        new=new.with_name(base+f' ({n}).md');n+=1
    mapping[key(p)] = key(new)
    new.write_text(content,encoding='utf-8')
    remove_backed_up(p)

for group in ('Люди','Темы','Компании','Проекты'):
    for p in list((root/'Связи'/group).glob('*.md')):
        content = p.read_text(encoding='utf-8')
        generated = content.startswith('# ') and 'Эту страницу можно дополнять своими заметками.' in content and len(content.splitlines()) <= 5
        if not generated: continue
        title = content.splitlines()[0][2:]
        if group in ('Люди','Темы'):
            # Only retain person pages referenced by freshly generated, evidence-filtered notes.
            referenced = group=='Люди' and not re.search(r'-[a-f0-9]{8}$',p.stem) and any(('[[%s|'%key(p)) in n.read_text(encoding='utf-8') for n in (root/'Заметки').glob('*/*.md'))
            if not referenced:
                mapping[key(p)] = None
                remove_backed_up(p)
                continue
        if re.search(r'-[a-f0-9]{8}$',p.stem):
            new=p.with_name(entity_name(title)+'.md')
            if not new.exists():new.write_text(content,encoding='utf-8')
            mapping[key(p)]=key(new)
            remove_backed_up(p)

for name in ('Бюджет','Долги'):
    p=root/'Финансы'/(name+' — автоматически.md')
    if p.exists():
        mapping[key(p)] = key(root/'Финансы'/(name+'.md'))
        remove_backed_up(p)

def relink(match):
    target, _, label=match.group(1).partition('|')
    if target not in mapping:return match.group(0)
    replacement=mapping[target]
    return (label or target.rsplit('/',1)[-1]) if replacement is None else '[['+replacement+('|' +label if label else '')+']]'
for p in root.rglob('*.md'):
    content=p.read_text(encoding='utf-8')
    content=re.sub(r'\[\[([^\]]+)\]\]',relink,content)
    content=re.sub(r'^ID: .+\n','',content,flags=re.M)
    p.write_text(content,encoding='utf-8')
ActionService(s,sessions,threading.RLock()).export()
(root/'Начать здесь.md').write_text('# Начать здесь\n\n'+provider.link(root/'Главная.md','Открыть главную страницу')+'\n',encoding='utf-8')
print('Layout migrated; original files and database backed up. No actions executed.')
