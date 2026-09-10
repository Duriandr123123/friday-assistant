import json
import time
from backend.tests.test_system import client,settings,upload
from backend.app.usage import record,summary
from backend.app.schemas import verbatim_content
from backend.tests.test_actions import intent
from backend.app.db import Recording,Action
from sqlalchemy import select

def test_pair_single_use_expiry_and_auth(client,monkeypatch):
    monkeypatch.setattr('backend.app.onboarding.addresses',lambda port:['http://100.64.0.1:8765'])
    assert client.post('/pair/create',json={'server':'http://100.64.0.1:8765'},headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.post('/pair/create',json={'server':'http://external.invalid'}).status_code==422
    result=client.post('/pair/create',json={'server':'http://100.64.0.1:8765'})
    assert result.status_code==200 and '<svg' in result.json()['svg']
    code=client.app.state.pair_code[0]
    assert client.post('/pair/claim',json={'code':'incorrect'}).status_code==403
    assert client.post('/pair/claim',json={'code':code},headers={'Authorization':''}).status_code==200
    assert client.post('/pair/claim',json={'code':code}).status_code==403
    client.app.state.pair_code=(code,time.monotonic()-1)
    assert client.post('/pair/claim',json={'code':code}).status_code==403

def test_usage_unknown_price_is_not_zero_and_cached_tokens(settings):
    record(settings,'example-model','responses','completed',{'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':400}})
    record(settings,'example-model','responses','unconfirmed')
    assert summary(settings)['rows'][0]['estimated_usd'] is None
    (settings.data_directory/'api-prices.json').write_text(json.dumps({'example-model':{'input':2,'cached':1,'output':8,'audio_minute':0}}))
    row=summary(settings)['rows'][0]
    assert abs(row['estimated_usd']-.0024)<1e-10 and row['unconfirmed']==1

def test_crash_after_action_export_never_duplicates_expense(client):
    processor=client.app.state.processor
    processor.settings.stt_provider='local';processor.settings.llm_provider='openai'
    content=verbatim_content('тест');content.actions=[intent('expense')]
    processor.llm.process=lambda *args:content
    client.put('/budget',json={'initial_minor':10000000})
    rid=upload(client).json()['id']
    original=processor.actions.export
    processor.actions.export=lambda:(_ for _ in ()).throw(OSError('simulated export failure'))
    processor.tick()
    with processor.sessions() as session:
        assert session.get(Recording,rid).status=='retry'
        assert len(list(session.scalars(select(Action))))==1
    processor.actions.export=original
    processor.recover();processor.tick();processor.actions.run_pending()
    assert client.get('/actions').json()['balance_minor']==9700000
    data=client.get('/recordings/'+rid).json()
    assert data['status']=='saved' and len(data['action_results'])==1
