"""Durable, idempotent local ledger. No bank transfers are performed."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from backend.app.db import Action, Preference, Recording
from backend.app.schemas import ActionIntent
from backend.app.storage import atomic_write
from backend.app.providers.notes import escape, MarkdownNotesProvider


def normalize(value):
    return ' '.join((value or '').casefold().split())


def snapshot(session):
    rows = list(session.scalars(select(Action).order_by(Action.created_at, Action.id)))
    active = [r for r in rows if r.status == 'applied']
    pref = session.get(Preference, 'budget')
    initial = pref.value['initial_minor'] if pref else None
    balance = None if initial is None else initial + sum(r.result.get('cash_delta',0) for r in active)
    debts = []
    for r in active:
        if r.payload['kind'] != 'debt_open': continue
        paid = sum(a.payload['amount_minor'] for a in active if a.result.get('debt_id') == r.id)
        debts.append({'id':r.id,'person':r.payload['person'],'direction':r.payload['direction'],
                      'initial_minor':r.payload['amount_minor'],'remaining_minor':r.payload['amount_minor']-paid,
                      'due_date':r.payload.get('due_date')})
    return {'initial_minor':initial,'balance_minor':balance,'currency':'KZT','debts':debts,
            'actions':[{'id':r.id,'recording_id':r.recording_id,'payload':r.payload,'status':r.status,
                        'result':r.result,'error':r.error} for r in rows]}


class ActionService:
    def __init__(self, settings, sessions, mutex, calendar=None):
        self.settings, self.sessions, self.mutex = settings, sessions, mutex
        self.calendar = calendar

    def stage(self, recording, content):
        with self.mutex, self.sessions.begin() as session:
            # Once a recording's action plan exists, reprocessing never executes a changed plan implicitly.
            if session.scalar(select(Action).where(Action.recording_id == recording.id).limit(1)): return
            for index, intent in enumerate(content.actions):
                session.add(Action(id=str(uuid5(NAMESPACE_URL,f'jarvis-action:{recording.id}:{index}')),
                    recording_id=recording.id,created_at=(datetime.fromisoformat(recording.captured_at).astimezone(timezone.utc)+timedelta(microseconds=index)).isoformat(),
                    payload=intent.model_dump(mode='json'),status='pending',result={}))

    def run_pending(self):
        with self.mutex:
            with self.sessions() as session:
                ids = list(session.scalars(select(Action.id).where(Action.status.in_(['pending','waiting']))
                    .order_by(Action.created_at, Action.id)))
            for aid in ids:
                self.apply(aid)
            self.export()

    def apply(self, aid):
        with self.mutex:
            with self.sessions.begin() as session:
                row = session.get(Action, aid)
                connected = self.calendar is not None and (not hasattr(self.calendar, 'status') or self.calendar.status()['connected'])
                if row and row.status in ('pending', 'waiting') and row.payload['kind']=='calendar' and connected:
                    row.result = {**row.result, 'calendar_attempted':True}
            self._apply(aid)

    def _apply(self, aid):
        with self.mutex, self.sessions.begin() as session:
            row = session.get(Action, aid)
            if row is None or row.status not in ('pending','waiting'): return
            a = ActionIntent.model_validate(row.payload)
            def wait(message, status='needs_input'):
                row.status, row.error = status, message
            if a.clarification:
                wait(a.clarification); return
            if a.kind == 'calendar':
                if not a.starts_at:
                    wait('Уточните дату и время встречи'); return
                if a.starts_at <= datetime.now(timezone.utc):
                    wait('Время встречи уже прошло. Уточните новую дату.'); return
                try:
                    if self.calendar is None: raise ValueError('Подключите Google Календарь')
                    row.result = self.calendar.create(row.id, a)
                    row.status, row.error = 'applied', None
                except Exception:
                    wait('Google Календарь недоступен или не подключён. Повторим после подключения.', 'waiting')
                return
            if a.currency != 'KZT' or a.amount_minor is None:
                wait('Уточните точную сумму в тенге'); return
            state = snapshot(session)
            delta = 0
            result = {}
            if a.kind in ('expense','income'):
                delta = a.amount_minor * (-1 if a.kind == 'expense' else 1)
            else:
                if not a.person or not a.direction:
                    wait('Уточните человека и кто кому должен'); return
                if a.kind == 'debt_payment':
                    matches = [d for d in state['debts'] if normalize(d['person']) == normalize(a.person)
                               and d['direction'] == a.direction and d['remaining_minor'] > 0]
                    if len(matches) != 1:
                        wait('Не найден единственный открытый долг. Уточните долг или внесите его сначала.'); return
                    debt = matches[0]
                    if a.amount_minor > debt['remaining_minor']:
                        wait('Погашение превышает остаток долга'); return
                    result['debt_id'] = debt['id']
                    if a.cash_moved: delta = a.amount_minor * (1 if a.direction == 'owed_to_me' else -1)
                elif a.cash_moved:
                    delta = a.amount_minor * (-1 if a.direction == 'owed_to_me' else 1)
            if delta and state['initial_minor'] is None:
                wait('Задайте начальный бюджет в разделе «Финансы»', 'waiting'); return
            result['cash_delta'] = delta
            row.result, row.status, row.error = result, 'applied', None

    def cancel(self, aid):
        with self.mutex, self.sessions.begin() as session:
            row = session.get(Action, aid)
            if row is None: raise ValueError('Действие не найдено')
            if row.status == 'cancelled': return
            if row.payload['kind'] == 'calendar' and row.result.get('calendar_attempted'):
                if self.calendar is None: raise ValueError('Подключите Google Календарь для проверки отмены')
                self.calendar.delete(row.id)
            if row.status == 'applied':
                children = [r for r in session.scalars(select(Action).where(Action.status=='applied'))
                            if r.result.get('debt_id') == aid]
                if children: raise ValueError('Сначала отмените погашения этого долга')
                if row.payload['kind'] == 'calendar':
                    if self.calendar is None: raise ValueError('Подключите Google Календарь для отмены')
                    self.calendar.delete(row.id)
            row.status, row.error = 'cancelled', None
        self.export()

    def export(self):
        with self.sessions() as session:
            state = snapshot(session)
            recordings = {r.id:r for r in session.scalars(select(Recording))}
        root = self.settings.notes_directory
        money = lambda v: 'не задан' if v is None else f'{v/100:,.2f} ₸'.replace(',', ' ')
        lines = ['# Бюджет', '', 'Эта сводка обновляется приложением. Изменения в Markdown не меняют учёт.',
                 '', 'Начальный бюджет: '+money(state['initial_minor']), 'Остаток: '+money(state['balance_minor']), '', '## Операции']
        linker = MarkdownNotesProvider(self.settings)
        category_totals = {}
        for a in state['actions']:
            if a['status']=='applied' and a['payload']['kind']=='expense':
                category = a['payload'].get('category') or 'Без категории'
                category_totals[category] = category_totals.get(category,0)+a['payload']['amount_minor']
        lines += [''] + [f'- {escape(k)}: {money(v)}' for k,v in sorted(category_totals.items())] + ['', '## Доходы и расходы']
        journal = ['# Журнал поручений', '', 'Действия из голосовых записей. Отмена и уточнение — в приложении.', '']
        labels = {'applied':'Выполнено','cancelled':'Отменено','pending':'В очереди','waiting':'Ожидает','needs_input':'Нужно уточнение'}
        for a in state['actions']:
            p = a['payload']; record = recordings.get(a['recording_id'])
            ref = linker.link(Path(record.markdown_path), 'Исходная запись') if record and record.markdown_path and Path(record.markdown_path).is_relative_to(root) else ''
            target = lines if p['kind'] in ('expense','income') else journal
            target.append(f"- {escape(p['description'])} — {money(p.get('amount_minor')) if p['kind']!='calendar' else 'встреча'}; {labels.get(a['status'], a['status'])}. {ref}")
            if a['error']: target.append('  - '+escape(a['error']))
        atomic_write(root/'Финансы'/'Бюджет.md', ('\n'.join(lines)+'\n').encode('utf-8'))
        atomic_write(root/'Журнал поручений.md', ('\n'.join(journal)+'\n').encode('utf-8'))
        debts = ['# Долги', '', 'Сводка приложения; отмена и исправления выполняются в приложении.']
        for direction, title in [('i_owe','Я должен'),('owed_to_me','Мне должны')]:
            debts += ['', '## '+title]
            selected = [d for d in state['debts'] if d['direction']==direction]
            debts += [f"- {escape(d['person'])}: остаток {money(d['remaining_minor'])}; срок: {escape(d['due_date'] or 'не задан')}" for d in selected] or ['Нет внесённых долгов.']
        atomic_write(root/'Финансы'/'Долги.md', ('\n'.join(debts)+'\n').encode('utf-8'))

        overview = ['# Сюзанна', '', '## Финансы', '',
            'Остаток: **'+money(state['balance_minor'])+'**', '',
            linker.link(root/'Финансы'/'Бюджет.md','Бюджет')+' · '+linker.link(root/'Финансы'/'Долги.md','Долги'),
            '', '## Ближайшие встречи', '']
        meetings = [a for a in state['actions'] if a['payload']['kind']=='calendar' and a['status']=='applied' and a['payload'].get('starts_at') and datetime.fromisoformat(a['payload']['starts_at']) >= datetime.now(timezone.utc)]
        for a in sorted(meetings,key=lambda a:a['payload']['starts_at']):
            date = datetime.fromisoformat(a['payload']['starts_at'])
            overview.append(f"- {date:%d.%m.%Y %H:%M} — {escape(a['payload']['description'])}")
        if not meetings: overview.append('Нет запланированных встреч из приложения.')
        overview += ['', linker.link(root/'Журнал поручений.md','Журнал поручений'), '', '## Последние заметки', '']
        for r in sorted(recordings.values(), key=lambda r:r.captured_at, reverse=True)[:20]:
            if r.markdown_path and Path(r.markdown_path).is_file():
                overview.append('- '+linker.link(Path(r.markdown_path),(r.result or {}).get('title','Заметка')))
        overview += ['', 'Финансы обновляются автоматически. Исправляйте операции через приложение.', '']
        atomic_write(root/'Главная.md', '\n'.join(overview).encode('utf-8'))
