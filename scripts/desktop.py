"""Manual desktop launcher. Closing the window stops its server; no startup tasks."""
import os
import sys
from pathlib import Path

home=Path(os.environ.get('FRIDAY_HOME',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'FridayAssistant'/'UserData')))
os.environ['FRIDAY_HOME']=str(home)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def smoke():
    from fastapi.testclient import TestClient
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        s=Settings(_env_file=None,api_token='smoke-only-token-abcdefghijklmnopqrstuvwxyz',data_directory=Path(d)/'data',notes_directory=Path(d)/'notes',stt_provider='mock',llm_provider='mock')
        with TestClient(create_app(s,worker=False)) as c:
            assert c.get('/health').status_code==200
            assert c.get('/').status_code==200
        import logging
        logging.shutdown()
    (home/'smoke-ok.txt').parent.mkdir(parents=True,exist_ok=True)
    (home/'smoke-ok.txt').write_text('ok')

def main():
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    import json,secrets,threading,webbrowser,time
    from backend.app.core.config import Settings
    home.mkdir(parents=True,exist_ok=True)
    config=home/'.env'
    settings=Settings(_env_file=config)
    root=tk.Tk();root.title('Пятница — сервер на компьютере');root.geometry('660x510')
    box=ttk.Frame(root,padding=20);box.pack(fill='both',expand=True)
    ttk.Label(box,text='Пятница',font=('Segoe UI',22)).pack(anchor='w')
    ttk.Label(box,text='Запуск вручную. Закрытие этого окна останавливает сервер.').pack(anchor='w',pady=8)
    fields={}
    for key,label,value,secret in [('key','Ваш OpenAI API-ключ',settings.openai_api_key.get_secret_value(),True),('model','Модель обработки OpenAI',settings.openai_llm_model,False),('notes','Папка заметок / папка внутри Obsidian',str(settings.notes_directory),False)]:
        ttk.Label(box,text=label).pack(anchor='w')
        v=tk.StringVar(value=value);fields[key]=v
        ttk.Entry(box,textvariable=v,show='*' if secret else '').pack(fill='x',pady=3)
    def choose():
        path=filedialog.askdirectory()
        if path:fields['notes'].set(path)
    ttk.Button(box,text='Выбрать папку заметок',command=choose).pack(anchor='w')
    status=tk.StringVar(value='Введите свои настройки. Облачная обработка оплачивается через ваш API-аккаунт.')
    ttk.Label(box,textvariable=status,wraplength=610).pack(anchor='w',pady=15)
    server=None; thread=None; running_settings=None
    def start():
        nonlocal server,thread,running_settings
        if thread and thread.is_alive():return
        if not fields['key'].get().strip() or not fields['model'].get().strip():
            messagebox.showerror('Настройки','Укажите свой API-ключ и модель обработки.');return
        path=Path(fields['notes'].get()).expanduser().resolve()
        try:
            path.mkdir(parents=True,exist_ok=True)
            token=(running_settings or settings).api_token.get_secret_value() or secrets.token_urlsafe(32)
            values={'API_TOKEN':token,'OPENAI_API_KEY':fields['key'].get().strip(),'OPENAI_LLM_MODEL':fields['model'].get().strip(),
                'STT_PROVIDER':'openai','LLM_PROVIDER':'openai','NOTES_DIRECTORY':str(path),'DATA_DIRECTORY':str(home/'data')}
            config.write_text('\n'.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in values.items())+'\n',encoding='utf-8')
            running_settings=Settings(_env_file=config)
            from backend.app.main import create_app
            import uvicorn
            server=uvicorn.Server(uvicorn.Config(create_app(running_settings),host='0.0.0.0',port=running_settings.port,access_log=False,log_config=None))
            def run():
                try:server.run()
                except BaseException:pass
            thread=threading.Thread(target=run,daemon=True);thread.start()
            status.set('Запуск сервера…')
            def ready(attempt=0):
                if server.started:
                    status.set('Сервер работает. Скопируйте токен и откройте панель. В панели доступен QR для телефона.');return
                if not thread.is_alive() or attempt>40:
                    status.set('Сервер не запущен. Возможно, другая копия уже использует порт 8765.');return
                root.after(250,lambda:ready(attempt+1))
            ready()
        except Exception:
            messagebox.showerror('Ошибка','Не удалось сохранить настройки или запустить сервер. Проверьте доступ к папке.')
    def stop():
        if server:server.should_exit=True
        status.set('Остановка сервера…')
    def close():
        stop()
        def done():
            if thread and thread.is_alive():root.after(200,done)
            else:root.destroy()
        done()
    def token_copy():
        if not running_settings:return
        root.clipboard_clear();root.clipboard_append(running_settings.api_token.get_secret_value());status.set('Токен скопирован. Вставьте его в панели на этом компьютере. Не передавайте посторонним.')
    row=ttk.Frame(box);row.pack(fill='x',pady=10)
    for label,cmd in [('Запустить',start),('Остановить',stop),('Скопировать токен',token_copy),('Открыть панель',lambda:webbrowser.open('http://127.0.0.1:8765/'))]:ttk.Button(row,text=label,command=cmd).pack(side='left',padx=3)
    ttk.Label(box,text='Google Календарь подключается отдельно в панели. Для мобильной сети нужен Tailscale на обоих устройствах.',wraplength=610).pack(anchor='w')
    root.protocol('WM_DELETE_WINDOW',close)
    root.mainloop()

if __name__=='__main__':
    if '--smoke-test' in sys.argv:
        try:smoke()
        except Exception:
            import traceback
            home.mkdir(parents=True,exist_ok=True)
            (home/'smoke-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            sys.exit(1)
    else:main()
