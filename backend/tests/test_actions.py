from types import SimpleNamespace
from pathlib import Path
import pytest
from sqlalchemy import select
from backend.tests.test_system import client, settings
from backend.app.schemas import ActionIntent, verbatim_content
from backend.app.db import Action, Preference
from backend.app.actions import snapshot


def intent(kind, **kw):
    return ActionIntent(kind=kind,evidence='тест',description='Операция',amount_minor=300000,
        currency='KZT',category='Еда',person=kw.get('person'),direction=kw.get('direction'),
        cash_moved=kw.get('cash_moved',True),due_date=None,starts_at=None,duration_minutes=None,
        reminder_minutes=None,clarification=kw.get('clarification'))


def stage(client, rid, a):
    content=verbatim_content('тест');content.actions=[a]
    service=client.app.state.processor.actions
    service.stage(SimpleNamespace(id=rid,captured_at='2026-09-10T12:00:00+05:00'),content)
    service.run_pending()
    return client.get('/actions').json()


def test_budget_waits_idempotency_and_undo(client):
    state=stage(client,'one',intent('expense'))
    assert state['balance_minor'] is None and state['actions'][0]['status']=='waiting'
    state=client.put('/budget',json={'initial_minor':5000000}).json()
    assert state['balance_minor']==4700000
    stage(client,'one',intent('expense'))
    assert client.get('/actions').json()['balance_minor']==4700000
    aid=state['actions'][0]['id']
    assert client.post(f'/actions/{aid}/cancel').json()['balance_minor']==5000000
    assert client.post(f'/actions/{aid}/cancel').json()['balance_minor']==5000000


def test_finance_export_links_saved_recording_without_reapplying(client, settings):
    from backend.tests.test_system import upload
    from backend.app.db import Recording
    rid = upload(client).json()['id']
    processor = client.app.state.processor
    assert processor.tick()
    client.put('/budget', json={'initial_minor':10000000})
    stage(client, rid, intent('expense'))
    processor.actions.run_pending()
    assert client.get('/actions').json()['balance_minor'] == 9700000
    with processor.sessions() as session:
        record = session.get(Recording, rid)
        expected = processor.notes.link(Path(record.markdown_path), 'Исходная запись')
    exported = (settings.notes_directory/'Финансы'/'Бюджет.md').read_text(encoding='utf-8')
    assert expected in exported


def test_debt_without_cash_partial_payment_and_dependencies(client):
    client.put('/budget',json={'initial_minor':5000000})
    state=stage(client,'debt',intent('debt_open',person='Алексей',direction='owed_to_me',cash_moved=False))
    assert state['balance_minor']==5000000
    debtid=state['debts'][0]['id']
    repayment=intent('debt_payment',person='Алексей',direction='owed_to_me');repayment.amount_minor=100000
    state=stage(client,'repay',repayment)
    assert state['balance_minor']==5100000
    assert state['debts'][0]['remaining_minor']==200000
    assert client.post(f'/actions/{debtid}/cancel').status_code==409
    paymentid=next(a['id'] for a in state['actions'] if a['payload']['kind']=='debt_payment')
    client.post(f'/actions/{paymentid}/cancel')
    assert client.post(f'/actions/{debtid}/cancel').status_code==200


def test_ambiguous_intent_never_applies(client):
    client.put('/budget',json={'initial_minor':5000000})
    state=stage(client,'unclear',intent('expense',clarification='Уточните сумму'))
    assert state['balance_minor']==5000000
    assert state['actions'][0]['status']=='needs_input'


def test_calendar_retry_idempotent_and_cancel_waiting(client):
    from datetime import datetime, timezone, timedelta
    class Calendar:
        def __init__(self):self.ids=set();self.calls=0
        def create(self,aid,a):
            self.ids.add(aid);self.calls+=1
            if self.calls==1:raise OSError('lost reply')
            return {'event_id':aid}
        def delete(self,aid):self.ids.discard(aid)
    cal=Calendar();client.app.state.processor.actions.calendar=cal
    a=intent('calendar');a.starts_at=datetime.now(timezone.utc)+timedelta(days=2)
    state=stage(client,'meeting',a)
    assert state['actions'][0]['status']=='waiting'
    client.post('/actions/retry')
    assert len(cal.ids)==1
    aid=state['actions'][0]['id']
    assert client.post(f'/actions/{aid}/cancel').status_code==200
    assert not cal.ids
