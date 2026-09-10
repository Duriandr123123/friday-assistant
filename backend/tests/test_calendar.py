from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import httpx
from backend.app.calendar import GoogleCalendar


def test_duplicate_event_reuses_id_and_zero_minute_reminder(tmp_path, monkeypatch):
    service=GoogleCalendar(SimpleNamespace(data_directory=tmp_path))
    monkeypatch.setattr(service,'access_token',lambda:'test-token')
    seen=[]
    aid='sample-action'
    def handler(request):
        seen.append(request)
        if request.method=='POST':return httpx.Response(409)
        return httpx.Response(200,json={'id':service.event_id(aid),'htmlLink':'https://calendar.google.com/',
            'extendedProperties':{'private':{'suzanna_action':aid}}})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    a=SimpleNamespace(description='Meeting',starts_at=datetime.now(timezone.utc)+timedelta(days=1),duration_minutes=45,reminder_minutes=0)
    result=service.create(aid,a)
    import json
    body=json.loads(seen[0].content)
    assert body['id']==result['event_id']
    assert body['reminders']['overrides'][0]['minutes']==0
    assert seen[1].url.path.endswith(result['event_id'])


def test_client_configuration_rejects_other_types(tmp_path):
    import pytest
    service=GoogleCalendar(SimpleNamespace(data_directory=tmp_path))
    with pytest.raises(ValueError): service.configure({'web':{'client_id':'x'}})
    assert not service.status()['connected']
