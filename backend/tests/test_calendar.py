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


def test_expired_permission_is_not_reported_as_connected(tmp_path,monkeypatch):
    import json
    import pytest
    (tmp_path/'google-client.json').write_text(json.dumps({'client_id':'test','client_secret':'test'}))
    (tmp_path/'google-token.json').write_text(json.dumps({'refresh_token':'test','expires_at':0}))
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:httpx.Response(400,json={'error':'invalid_grant'},request=httpx.Request('POST','https://oauth2.googleapis.com/token')))
    service=GoogleCalendar(SimpleNamespace(data_directory=tmp_path))
    with pytest.raises(httpx.HTTPStatusError): service.access_token()
    assert not service.status()['connected']
    assert service.status()['reauth_required']
    assert (tmp_path/'google-token.json').exists()


def test_packaged_client_is_pinned_and_preserves_existing_connection(tmp_path, monkeypatch):
    import json
    import backend.app.calendar as module
    bundled = tmp_path/'bundle.json'
    bundled.write_text(json.dumps({'installed': {'client_id':'first.apps.googleusercontent.com', 'client_secret':'test'}}))
    monkeypatch.setattr(module, 'PACKAGED_CLIENT', bundled)
    root = tmp_path/'user'
    root.mkdir()
    service = GoogleCalendar(SimpleNamespace(data_directory=root))
    assert service.status()['client_configured']
    assert service.client()['client_id'] == 'first.apps.googleusercontent.com'
    bundled.write_text('{}')
    assert service.client()['client_id'] == 'first.apps.googleusercontent.com'
    (root/'google-token.json').write_text('{"refresh_token":"test"}')
    (root/'google-client.json').unlink()
    import pytest
    with pytest.raises(ValueError, match='Google'):
        service.client()
