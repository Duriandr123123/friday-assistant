"""Usage counts only: never stores request text, audio, keys, or raw error bodies."""
import sqlite3
import json
from datetime import datetime,timezone

def connect(settings):
    settings.data_directory.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(settings.data_directory/'usage.sqlite3',timeout=15)
    c.execute('CREATE TABLE IF NOT EXISTS usage(at TEXT, model TEXT, endpoint TEXT, status TEXT, counts TEXT)')
    return c

def record(settings,model,endpoint,status,counts=None):
    try:
        with connect(settings) as c:
            c.execute('INSERT INTO usage VALUES(?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),str(model),endpoint,status,json.dumps(counts or {})))
    except sqlite3.Error:
        # Metrics must not cause a paid request to be retried.
        pass

def summary(settings):
    groups={}
    with connect(settings) as c:
        for model,endpoint,status,counts in c.execute('SELECT model,endpoint,status,counts FROM usage'):
            key=(model,endpoint)
            row=groups.setdefault(key,dict(model=model,endpoint=endpoint,requests=0,unconfirmed=0,input_tokens=0,output_tokens=0,cached_tokens=0,audio_seconds=0))
            row['requests']+=1
            if status!='completed':row['unconfirmed']+=1
            u=json.loads(counts)
            for name in ('input_tokens','output_tokens','audio_seconds'):row[name]+=u.get(name,0) or 0
            row['cached_tokens']+=(u.get('input_tokens_details') or {}).get('cached_tokens',0) or 0
    p=settings.data_directory/'api-prices.json'
    prices=json.loads(p.read_text()) if p.exists() else {}
    for row in groups.values():
        rate=prices.get(row['model'])
        row['estimated_usd']=None
        if rate:
            if row['endpoint']=='responses':
                row['estimated_usd']=((row['input_tokens']-row['cached_tokens'])*rate['input']+row['cached_tokens']*rate['cached']+row['output_tokens']*rate['output'])/1e6
            elif row['audio_seconds']:row['estimated_usd']=row['audio_seconds']/60*rate['audio_minute']
    return {'rows':list(groups.values()),'prices':prices,'notice':'Оценка по введённым тарифам, не счёт OpenAI. Неопределённые запросы могут быть оплачены; сверяйте кабинет провайдера. Учёт начат с этого обновления.'}
