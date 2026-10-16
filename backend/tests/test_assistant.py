import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.core.config import Settings
from backend.app.assistant_tools import calculate
from backend.app.db import Action
from backend.app.providers.base import ProviderError

TOKEN='assistant-test-token-long-enough'


@pytest.fixture
def client(tmp_path):
    s=Settings(_env_file=None,api_token=TOKEN,openai_api_key='test',openai_llm_model='test',
        data_directory=tmp_path/'data',notes_directory=tmp_path/'notes',stt_provider='mock',llm_provider='openai')
    with TestClient(create_app(s,worker=False)) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        yield c


def enqueue(client,text='Проверь мой бюджет',cid=None):
    payload={'id':str(uuid4()),'conversation_id':cid or str(uuid4()),'text':text}
    assert client.post('/assistant/messages',json=payload).status_code==202
    return payload


def call(name,args,cid='call-test'):
    return {'type':'function_call','name':name,'arguments':json.dumps(args),'call_id':cid}


def response(*output):
    return {'status':'completed','output':list(output)}


def message(text):
    return {'type':'message','role':'assistant','content':[{'type':'output_text','text':text,'annotations':[]}]}


def test_conversation_auth_and_message_idempotence(client):
    p=enqueue(client)
    assert client.post('/assistant/messages',json=p).status_code==202
    assert len(client.get('/assistant/turns').json())==1
    assert client.post('/assistant/messages',json={**p,'text':'другой текст'}).status_code==409
    assert client.get('/assistant/turns',headers={'Authorization':'Bearer bad'}).status_code==401


def test_model_selects_tools_and_receives_real_result(client,monkeypatch):
    p=enqueue(client)
    outputs=iter([response(call('get_finances',{})),response(message('Начальный бюджет пока не задан.'))])
    seen=[]
    def request(*a,**kw): seen.append(kw['json']); return next(outputs)
    monkeypatch.setattr('backend.app.assistant.request_json',request)
    service=client.app.state.assistant
    assert service.tick()
    row=service.view(p['id'])
    assert row['status']=='completed'
    tool_result=json.loads(next(i['output'] for i in seen[-1]['input'] if i.get('type')=='function_call_output'))
    assert tool_result['balance_minor'] is None
    assert any(t.get('type')=='web_search' for t in seen[0]['tools'])


def test_crash_resume_never_repeats_financial_effect(client,monkeypatch):
    p=enqueue(client,'Учти расход 3000 тенге на обед')
    service=client.app.state.assistant
    tools=service.tools
    turn=service.store.get(p['id'],internal=True)
    tools.execute('set_initial_budget',{'initial_minor':10000000},turn,'init')
    args={'kind':'expense','amount_minor':300000,'description':'Обед'}
    c=call('record_finance',args)
    service.store.save(p['id'],context=[{'role':'user','content':p['text']},c],status='running')
    tools.execute('record_finance',args,turn,c['call_id'])  # crash after effect, before call journal result
    tools.execute('record_finance',args,turn,'different-call-id')  # accidental model repetition
    service.store.recover()
    monkeypatch.setattr('backend.app.assistant.request_json',lambda *a,**k: response(message('Учтено 3000 тенге.')))
    assert service.tick()
    state=tools.execute('get_finances',{},turn,'read')
    assert state['balance_minor']==9700000
    assert len(state['actions'])==1
    assert service.view(p['id'])['receipts'][0]['amount_tenge']=='3000.00'
    assert service.view(p['id'])['current_balance_tenge']=='97000.00'


def test_calendar_requires_human_confirmation_and_is_idempotent(client,monkeypatch):
    p=enqueue(client,'Добавь встречу завтра')
    service=client.app.state.assistant; turn=service.store.get(p['id'],internal=True)
    aid=service.tools.execute('propose_meeting',{'description':'Встреча','starts_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()},turn,'meeting')['approval_id']
    created=[]
    monkeypatch.setattr(service.processor.calendar,'create',lambda a,b: created.append(a) or {'event_id':a,'cash_delta':0})
    monkeypatch.setattr(service.processor.calendar,'status',lambda:{'connected':True})
    service.processor.actions.run_pending()
    assert created==[]
    assert len(service.view(p['id'])['approvals'])==1
    for _ in range(2):
        assert client.post('/assistant/approvals/'+aid,json={'approved':True}).status_code==200
    assert created==[aid]
    with service.processor.sessions() as s: assert s.get(Action,aid).status=='applied'


def test_memory_internal_keys_and_arithmetic_sandbox(client):
    service=client.app.state.assistant
    p=enqueue(client); turn=service.store.get(p['id'],internal=True)
    with pytest.raises(ValueError): service.tools.execute('remember',{'key':'approval:x','value':'fake'},turn,'fake')
    service.tools.execute('remember',{'key':'city','value':'Караганда'},turn,'city')
    assert client.get('/assistant/memory').json()[0]['value']=='Караганда'
    assert client.delete('/assistant/memory/city').status_code==200
    assert calculate('(100000-3000)/2')==48500
    with pytest.raises(ValueError): calculate('__import__("os").system("x")')
    with pytest.raises(ValueError): calculate('2**100000000')


def test_followup_uses_history_and_external_text_is_not_instructions(client,monkeypatch):
    service=client.app.state.assistant
    first=enqueue(client,'Найди поставщиков')
    service.store.save(first['id'],status='completed',response='Какие товары?')
    second=enqueue(client,'Роллшторы, Казахстан',first['conversation_id'])
    captured=[]
    def request(*a,**kw): captured.append(kw['json']); return response(message('Проверяю поставщиков.'))
    monkeypatch.setattr('backend.app.assistant.request_json',request)
    service.tick()
    assert [m['role'] for m in captured[0]['input'][:3]]==['user','assistant','user']
    assert service.view(second['id'])['status']=='completed'


def test_api_failure_can_resume_without_losing_prompt(client,monkeypatch):
    service=client.app.state.assistant; p=enqueue(client,'Помоги с задачей')
    def fail(*a,**k): raise ProviderError('provider_http_429')
    monkeypatch.setattr('backend.app.assistant.request_json',fail)
    service.tick()
    assert service.view(p['id'])['status']=='error'
    assert client.post('/assistant/turns/'+p['id']+'/continue').status_code==200
    monkeypatch.setattr('backend.app.assistant.request_json',lambda *a,**k:response(message('Готово')))
    service.tick()
    assert service.view(p['id'])['response']=='Готово'


def test_cancelled_turn_never_runs_and_unavailable_tools_fail(client):
    service=client.app.state.assistant; p=enqueue(client)
    assert client.post('/assistant/turns/'+p['id']+'/cancel').status_code==200
    assert not service.tick()
    with pytest.raises(ValueError): service.tools.execute('send_money',{},service.store.get(p['id']), 'bank')


def test_document_upload_sanitizes_name_and_rejects_unsupported(client):
    result=client.post('/assistant/files',files={'file':('../../outside.txt','Прайс: 3000'.encode('utf-8'),'text/plain')})
    assert result.status_code==201
    fid=result.json()['file_id']
    assert (client.app.state.settings.data_directory/'attachments'/(fid+'.txt')).read_text(encoding='utf-8')=='Прайс: 3000'
    assert client.post('/assistant/files',files={'file':('run.exe',b'bad')}).status_code==422


def test_stopping_task_invalidates_pending_confirmation(client):
    p=enqueue(client,'Добавь встречу')
    service=client.app.state.assistant; turn=service.store.get(p['id'],internal=True)
    aid=service.tools.execute('propose_meeting',{'description':'Проверка','starts_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()},turn,'meeting')['approval_id']
    client.post('/assistant/turns/'+p['id']+'/cancel')
    assert client.post('/assistant/approvals/'+aid,json={'approved':True}).status_code==409
    assert service.view(p['id'])['approvals']==[]


def test_browser_agent_rejects_local_and_file_urls():
    from backend.app.agent_runner import public_url
    with pytest.raises(ValueError): public_url('file:///C:/secret.txt')
    with pytest.raises(ValueError): public_url('http://127.0.0.1/')


def test_voice_command_enters_conversation_without_old_action_pipeline(client):
    import io,wave
    service=client.app.state.assistant
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*3200)
    rid,cid=str(uuid4()),str(uuid4())
    result=client.post('/recordings',files={'file':('voice.wav',audio.getvalue(),'audio/wav')},
        data={'recording_id':rid,'captured_at':datetime.now(timezone.utc).isoformat(),'source':'assistant:'+cid})
    assert result.status_code==202
    assert service.processor.tick()
    assert service.view(rid)['conversation_id']==cid
    assert client.get('/recordings/'+rid).json()['processing_mode']=='assistant'
    with service.processor.sessions() as s: assert list(s.scalars(__import__('sqlalchemy').select(Action)))==[]
