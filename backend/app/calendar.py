"""Google Calendar desktop OAuth with loopback callback and PKCE."""
import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
from backend.app.storage import atomic_write

SCOPE = 'https://www.googleapis.com/auth/calendar.events.owned'


class GoogleCalendar:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_directory
        self.lock = threading.RLock()
        self.oauth = None
        self.last_error = None

    def status(self):
        return {'client_configured': (self.root/'google-client.json').exists(),
                'connected': (self.root/'google-token.json').exists(),
                'connecting': self.oauth is not None, 'error':self.last_error}

    def configure(self, payload):
        installed = payload.get('installed', {})
        cid, secret = installed.get('client_id'), installed.get('client_secret')
        if not isinstance(cid,str) or not cid.endswith('.apps.googleusercontent.com') or not isinstance(secret,str):
            raise ValueError('Нужен JSON OAuth-клиента Google типа Desktop app')
        with self.lock:
            if self.oauth: raise ValueError('Дождитесь завершения текущего подключения')
            atomic_write(self.root/'google-client.json',json.dumps({'client_id':cid,'client_secret':secret}).encode())
            (self.root/'google-token.json').unlink(missing_ok=True)

    def begin(self):
        with self.lock:
            if self.oauth: raise ValueError('Окно подключения уже открыто')
            client = json.loads((self.root/'google-client.json').read_text())
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            owner = self
            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_GET(self):
                    query = parse_qs(urlparse(self.path).query)
                    if not secrets.compare_digest(query.get('state',[''])[0],state):
                        self.send_error(400); return
                    try:
                        code = query.get('code',[''])[0]
                        if not code: raise ValueError('Access not granted')
                        response = httpx.post('https://oauth2.googleapis.com/token',data={**client,
                            'code':code,'code_verifier':verifier,'redirect_uri':redirect,
                            'grant_type':'authorization_code'},timeout=30)
                        response.raise_for_status()
                        token = response.json()
                        if not token.get('refresh_token'): raise ValueError('Missing refresh token')
                        token['expires_at'] = time.time()+token.get('expires_in',3600)
                        atomic_write(owner.root/'google-token.json',json.dumps(token).encode())
                        owner.last_error = None
                        message = 'Google Calendar connected. You may close this window.'
                    except Exception:
                        owner.last_error = 'Не удалось подключить Google. Повторите вход.'
                        message = 'Connection failed. Please retry in the app.'
                    self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8'); self.end_headers()
                    self.wfile.write(message.encode())
                    server.finished = True
            server = HTTPServer(('127.0.0.1',0),Callback)
            server.timeout = 1
            server.finished = False
            redirect = f'http://127.0.0.1:{server.server_port}/'
            self.oauth = server
            def listen():
                try:
                    deadline = time.time()+300
                    while not server.finished and time.time()<deadline: server.handle_request()
                finally:
                    server.server_close()
                    with owner.lock: owner.oauth = None
            threading.Thread(target=listen,daemon=True,name='google-login').start()
            return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({
                'client_id':client['client_id'],'redirect_uri':redirect,'response_type':'code',
                'scope':SCOPE,'state':state,'code_challenge':challenge,'code_challenge_method':'S256',
                'access_type':'offline','prompt':'consent'})

    def access_token(self):
        with self.lock:
            token = json.loads((self.root/'google-token.json').read_text())
            if token.get('expires_at',0) < time.time()+60:
                client = json.loads((self.root/'google-client.json').read_text())
                response = httpx.post('https://oauth2.googleapis.com/token',data={**client,
                    'grant_type':'refresh_token','refresh_token':token['refresh_token']},timeout=30)
                response.raise_for_status(); token.update(response.json())
                token['expires_at'] = time.time()+token.get('expires_in',3600)
                atomic_write(self.root/'google-token.json',json.dumps(token).encode())
            return token['access_token']

    def event_id(self, aid):
        return hashlib.sha256(('suzanna:'+aid).encode()).hexdigest()

    def create(self, aid, action):
        event_id = self.event_id(aid)
        body = {'id':event_id,'summary':action.description,
            'start':{'dateTime':action.starts_at.isoformat()},
            'end':{'dateTime':(action.starts_at+timedelta(minutes=action.duration_minutes or 60)).isoformat()},
            'reminders':{'useDefault':False,'overrides':[{'method':'popup','minutes':30 if action.reminder_minutes is None else action.reminder_minutes}]},
            'extendedProperties':{'private':{'suzanna_action':aid}}}
        with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+self.access_token()}) as client:
            url = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
            response = client.post(url,params={'sendUpdates':'none'},json=body)
            if response.status_code == 409:
                response = client.get(url+'/'+event_id)
            response.raise_for_status(); event = response.json()
            if event.get('status') == 'cancelled': raise ValueError('Event cancelled externally')
            if event.get('extendedProperties',{}).get('private',{}).get('suzanna_action') != aid:
                raise ValueError('Event identifier mismatch')
            return {'event_id':event_id,'url':event.get('htmlLink',''),'cash_delta':0}

    def delete(self, aid):
        with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+self.access_token()}) as client:
            url = 'https://www.googleapis.com/calendar/v3/calendars/primary/events/'+self.event_id(aid)
            current = client.get(url)
            if current.status_code in (404,410): return
            current.raise_for_status()
            if current.json().get('extendedProperties',{}).get('private',{}).get('suzanna_action') != aid:
                raise ValueError('Event identifier mismatch')
            response = client.delete(url,params={'sendUpdates':'none'})
            if response.status_code not in (404,410): response.raise_for_status()
