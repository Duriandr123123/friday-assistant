"""Isolated optional GitHub components; never execute model-supplied shell commands."""
import json
import os
import subprocess
import threading
from pathlib import Path


PROJECTS={
    'research':('gpt-researcher','https://github.com/assafelovic/gpt-researcher'),
    'browser':('browser-use','https://github.com/browser-use/browser-use'),
    'memory':('mem0ai','https://github.com/mem0ai/mem0'),
    'document':('markitdown','https://github.com/microsoft/markitdown'),
    'google':('workspace-mcp','https://github.com/taylorwilsdon/google_workspace_mcp'),
}
_children=set()
_lock=threading.RLock()


def stop_active():
    with _lock: processes=list(_children)
    for process in processes:
        if process.poll() is not None: continue
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else: process.kill()


def capabilities(settings):
    manifest=settings.agents_python.parent.parent/'friday-components.json'
    try: installed=json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError,ValueError): installed={}
    google_root=settings.agents_python.parent.parent.parent/'google-workspace-mcp'
    try: installed.update(json.loads((google_root/'friday-components.json').read_text(encoding='utf-8')))
    except (OSError,ValueError): pass
    def available(kind,package):
        executable=google_root/'Scripts'/'python.exe' if kind=='google' else settings.agents_python
        return bool(installed.get(package) and executable.is_file())
    return [{'kind':kind,'project':package,'url':url,'version':installed.get(package),
             'installed':available(kind,package),
             'enabled':available(kind,package) and kind!='google',
             'note':'Нужна отдельная авторизация Google; текущий календарь работает через прежнее подключение.' if kind=='google' else ''}
            for kind,(package,url) in PROJECTS.items()]


def invoke(settings,kind,payload):
    if kind not in {'research','browser','document','memory_search','memory_add'}:
        raise ValueError('Unsupported integration')
    expected='memory' if kind.startswith('memory_') else kind
    if not any(c['kind']==expected and c['enabled'] for c in capabilities(settings)):
        return {'error':'Компонент не установлен. Используйте доступные инструменты или настройте дополнения.'}
    keep={'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA',
          'PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','COMSPEC','PATHEXT',
          'SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','HTTPS_PROXY','HTTP_PROXY','NO_PROXY'}
    env={k:v for k,v in os.environ.items() if k.upper() in keep}
    work=(settings.data_directory/'agents').resolve()
    work.mkdir(parents=True,exist_ok=True)
    env.update({'OPENAI_API_KEY':settings.openai_api_key.get_secret_value(),
        'OPENAI_BASE_URL':settings.openai_base_url,'FRIDAY_AGENT_MODEL':settings.openai_agent_model or settings.openai_llm_model,
        'FRIDAY_AGENT_DATA':str(work), 'PYTHONIOENCODING':'utf-8','PYTHON_DOTENV_DISABLED':'1',
        'MEM0_TELEMETRY':'false','ANONYMIZED_TELEMETRY':'false','BROWSER_USE_TELEMETRY':'false','DO_NOT_TRACK':'1'})
    runner=Path(__file__).with_name('agent_runner.py').resolve()
    # Fixed executable/script, JSON stdin and a dedicated browser profile; never a shell string.
    process=None
    try:
        bootstrap='import runpy,sys; runpy.run_path(sys.argv[1],run_name="__main__")'
        process=subprocess.Popen([str(settings.agents_python),'-X','utf8','-c',bootstrap,str(runner)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            encoding='utf-8',errors='replace',env=env,cwd=work,
            creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0)
        with _lock: _children.add(process)
        try:
            stdout,_=process.communicate(json.dumps({'kind':kind,**payload},ensure_ascii=False),timeout=240)
        except subprocess.TimeoutExpired:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
            else: process.kill()
            process.communicate(timeout=15)
            return {'error':'Время работы агента истекло. Можно уточнить запрос или использовать основной поиск.'}
        marker='FRIDAY_RESULT:'
        for line in reversed(stdout.splitlines()):
            if line.startswith(marker): return json.loads(line[len(marker):])
        return {'error':'Агент завершился без результата. Проверьте окружение дополнений.'}
    except subprocess.TimeoutExpired:
        return {'error':'Время работы агента истекло. Можно уточнить запрос или использовать основной поиск.'}
    finally:
        if process is not None:
            with _lock: _children.discard(process)
