'use strict';
const $ = id => document.getElementById(id);
let token = '', selected = null, offset = 0, editing = null, audioUrl = null;
const statuses = {queued:'В очереди',processing:'Обрабатываю',retry:'Повтор после ошибки',saved:'Сохранено',awaiting_ai:'Расшифровано · ожидает AI',failed:'Ошибка обработки'};
const errors = {llm_model_missing:'В файле .env не указана модель OPENAI_LLM_MODEL.',api_key_missing:'В файле .env не заполнена строка OPENAI_API_KEY. Вставьте секретный API-ключ сразу после знака =, в той же строке, и перезапустите сервер.',provider_http_401:'OpenAI не принял API-ключ. Проверьте секретный ключ в .env.',provider_http_429:'OpenAI ограничил запросы. Проверьте доступные средства и лимиты API-аккаунта.'};
function notice(text){$('notice').textContent=text;}
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{Authorization:`Bearer ${token}`,...options.headers}});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Ошибка ${response.status}`);}
  return response.status===204?null:response;
}
function node(tag, text, className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
async function load(append=false){
  try{
    const rows=await(await api(`/recordings?q=${encodeURIComponent($('search').value)}&limit=50&offset=${append?offset:0}`)).json();
    if(!append){$('records').replaceChildren();offset=0;}
    offset+=rows.length;$('count').textContent=`Показано записей: ${offset}`;$('more').hidden=rows.length<50;
    if(offset===0)$('records').append(node('p','Пока нет записей. Запишите мысль на телефоне или добавьте текст.','muted'));
    for(const row of rows){const b=node('button',undefined,'record'+(selected===row.id?' selected':''));
      b.append(node('small',new Date(row.captured_at).toLocaleString('ru-RU')),node('b',row.result?.title||'Голосовая мысль'),node('small',statuses[row.status]||row.status));
      b.onclick=()=>open(row.id);$('records').append(b);}
  }catch(e){notice(e.message);}
}
function addSection(root, title, values){if(!values?.length)return;root.append(node('h3',title));const list=node('ul');for(const value of values)list.append(node('li',value));root.append(list);}
async function open(id){
  try{
    const row=await(await api(`/recordings/${id}`)).json();selected=id;const d=$('detail');d.replaceChildren();
    if(audioUrl){URL.revokeObjectURL(audioUrl);audioUrl=null;}
    d.append(node('span',statuses[row.status]||row.status,'badge'));
    if(row.processing_mode==='mock')d.append(node('span','Тестовые данные','badge'));
    if(row.source==='e2e-test')d.append(node('span','Аудио для проверки системы','badge'));
    d.append(node('h2',row.result?.title||'Голосовая мысль'),node('p',new Date(row.captured_at).toLocaleString('ru-RU'),'muted'));
    if(row.error)d.append(node('p',`${errors[row.error] || 'Ошибка: '+row.error}. Исходная запись сохранена.`));
    const actions=node('div',undefined,'actions');
    function action(label, fn){const b=node('button',label,'secondary');b.onclick=()=>Promise.resolve(fn()).catch(e=>notice(e.message));actions.append(b);}
    action('Обновить',()=>open(id));
    action('Повторить обработку',async()=>{await api(`/process/${id}`,{method:'POST'});notice('Запись поставлена в очередь');await open(id);await load();});
    action('Исправить текст',()=>{editing=id;$('editor-title').textContent='Исправить расшифровку';$('transcript').value=row.edited_transcript??row.raw_transcript??'';$('editor').showModal();});
    if(row.has_markdown)action('Скачать Markdown',async()=>{const blob=await(await api(`/notes/${id}/markdown`)).blob();const url=URL.createObjectURL(blob);const a=node('a');a.href=url;a.download=`${id}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
    action('Удалить',()=>$('delete-dialog').showModal());d.append(actions);
    if(row.has_audio){const b=node('button','Прослушать аудио','secondary');b.onclick=async()=>{try{b.disabled=true;const blob=await(await api(`/recordings/${id}/audio`)).blob();if(selected!==id)return;audioUrl=URL.createObjectURL(blob);const a=node('audio');a.controls=true;a.src=audioUrl;b.replaceWith(a);a.play().catch(()=>{});}catch(e){notice(e.message);b.disabled=false;}};d.append(b);}
    const result=row.result;
    if(result){d.append(node('h3','Кратко'),node('p',result.summary,'prose'));
      addSection(d,'Задачи',result.tasks.map(t=>`${t.status==='done'?'✓':'□'} ${t.text}${t.deadline?' — '+t.deadline:''}`));
      for(const [title,field] of [['Главное','important_points'],['Проекты','projects'],['Люди','people'],['Компании','companies'],['Идеи','ideas'],['Решения','decisions'],['Вопросы','questions'],['Неопределённость','uncertainties']])addSection(d,title,result[field]);
      d.append(node('h3','Исправленный текст'),node('p',result.clean_transcript,'prose'));}
    if(row.raw_transcript!==null)d.append(node('h3','Исходная расшифровка'),node('p',row.raw_transcript,'prose'));
  }catch(e){notice(e.message);}
}
$('login-form').onsubmit=async e=>{e.preventDefault();token=$('token').value.trim();try{const s=await(await api('/settings/status')).json();$('provider-state').textContent=s.llm_provider==='pending'?'Расшифровки сохраняются. AI-конспекты появятся после подключения ключа.':`Распознавание: ${s.stt_provider} · AI: ${s.llm_provider}`;$('token').value='';$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;notice('');await load();}catch(e){notice(e.message);token='';}};
$('logout').onclick=()=>{token='';selected=null;$('workspace').hidden=true;$('login').hidden=false;$('logout').hidden=true;$('records').replaceChildren();$('detail').replaceChildren();if(audioUrl)URL.revokeObjectURL(audioUrl);notice('');};
$('search-form').onsubmit=e=>{e.preventDefault();load();};$('refresh').onclick=()=>load();$('more').onclick=()=>load(true);
$('new-note').onclick=()=>{editing=null;$('editor-title').textContent='Записать мысль';$('transcript').value='';$('editor').showModal();};
$('cancel').onclick=()=>$('editor').close();
$('edit-form').onsubmit=async e=>{e.preventDefault();try{const r=await(await api(editing?`/recordings/${editing}/transcript`:'/texts',{method:editing?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:$('transcript').value})})).json();$('editor').close();notice('Текст сохранён. Обработка начнётся автоматически.');await load();await open(r.id);}catch(e){notice(e.message);}};
$('cancel-delete').onclick=()=>$('delete-dialog').close();$('confirm-delete').onclick=async()=>{try{await api(`/recordings/${selected}`,{method:'DELETE'});selected=null;$('detail').replaceChildren();$('delete-dialog').close();notice('Запись удалена с компьютера');await load();}catch(e){notice(e.message);}};
// Optional browser agent surface uses the same authenticated API and UI state.
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  try{Promise.resolve(document.modelContext.registerTool({
    name:'search_notes',title:'Найти заметки',description:'Найти сохранённые заметки по словам после входа в панель.',
    inputSchema:{type:'object',properties:{query:{type:'string',maxLength:300}},required:['query'],additionalProperties:false},
    annotations:{readOnlyHint:true,untrustedContentHint:true},
    async execute(input){if(!token)throw Error('Сначала войдите в панель');if(!input||typeof input.query!=='string'||input.query.length>300)throw Error('Некорректный запрос');$('search').value=input.query;await load();const rows=await(await api(`/notes?q=${encodeURIComponent(input.query)}&limit=50`)).json();return rows.map(r=>({id:r.id,title:r.result?.title||'Голосовая мысль',status:r.status}));}
  },{signal:lifecycle.signal})).catch(()=>{});}catch{}
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
