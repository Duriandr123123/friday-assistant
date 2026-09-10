"""Short-lived, single-use pairing. No credential is placed in a URL."""
import secrets
import threading
import time
import socket
import ipaddress
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from backend.app.api import authorize
from fastapi import Depends

router = APIRouter()

def addresses(port):
    ips = {item[4][0] for item in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)}
    return [f'http://{ip}:{port}' for ip in sorted(ips) if not ip.startswith('127.')]

def local(request):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Откройте подключение на самом компьютере')

@router.get('/pair/addresses',dependencies=[Depends(authorize)])
def choices(request:Request):
    local(request)
    return {'addresses':addresses(request.app.state.settings.port)}

@router.post('/pair/create',dependencies=[Depends(authorize)])
def create(request:Request,payload:dict):
    local(request)
    address=payload.get('server','')
    if address not in addresses(request.app.state.settings.port):
        raise HTTPException(422,'Выберите адрес этого компьютера')
    with request.app.state.pair_lock:
        code=secrets.token_urlsafe(32)
        request.app.state.pair_code=(code,time.monotonic()+120)
    import qrcode, qrcode.image.svg, io, json
    data=json.dumps({'type':'friday-pair-v1','server':address,'code':code})
    image=qrcode.make(data,image_factory=qrcode.image.svg.SvgPathImage)
    out=io.BytesIO();image.save(out)
    return {'svg':out.getvalue().decode(),'expires_in':120}

@router.post('/pair/claim')
def claim(request:Request,payload:dict):
    code=payload.get('code')
    if not isinstance(code,str) or len(code)>100:raise HTTPException(400,'Неверный код')
    with request.app.state.pair_lock:
        pending=request.app.state.pair_code
        if not pending or time.monotonic()>pending[1] or not secrets.compare_digest(code,pending[0]):
            raise HTTPException(403,'Код истёк или уже использован. Создайте новый QR на компьютере.')
        request.app.state.pair_code=None
    return {'token':request.app.state.settings.api_token.get_secret_value(),'service':'jarvis-thoughts'}
