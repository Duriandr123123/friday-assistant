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

$('import-audio').onclick=()=>$('audio-files').click();
$('audio-files').onchange=async()=>{
 const files=Array.from($('audio-files').files); $('import-audio').disabled=true;
 let done=0; const failures=[];
 try { for(const file of files){
  notice(`Импорт: ${file.name}`);
  const body=new FormData(); body.append('file',file); body.append('captured_at',new Date(file.lastModified||Date.now()).toISOString());
  try { await api('/imports/audio',{method:'POST',body}); done++; }
  catch(e){ failures.push(`${file.name}: ${e.message}`); }
 }
 await load(); notice(`Импортировано файлов: ${done}. Обработка в очереди. ${failures.join('; ')}`);
 } finally { $('import-audio').disabled=false; $('audio-files').value=''; }
};

const actionLabels={expense:'Расход',income:'Доход',debt_open:'Новый долг',debt_payment:'Погашение долга',calendar:'Встреча'};
const actionStates={pending:'В очереди',waiting:'Ожидает подключения или бюджета',needs_input:'Нужно уточнение',applied:'Выполнено',cancelled:'Отменено'};
const money=v=>v===null?'не задан':(v/100).toLocaleString('ru-RU',{minimumFractionDigits:2})+' ₸';
async function loadActions(){
 try {
 const state=await(await api('/actions')).json();
 $('budget-summary').textContent=`Начальный бюджет: ${money(state.initial_minor)}. Остаток: ${money(state.balance_minor)}.`;
 $('calendar-state').textContent=state.calendar.connected?'Google: разрешение сохранено; доступ проверяется при отправке.':state.calendar.connecting?'Google: ожидается вход в открытом окне.':'Google Календарь пока не подключён.';
 $('debt-list').replaceChildren(node('h3','Долги'));
 for(const d of state.debts)$('debt-list').append(node('p',`${d.direction==='i_owe'?'Я должен':'Мне должны'} · ${d.person}: ${money(d.remaining_minor)}${d.due_date?' · срок '+d.due_date:''}`));
 $('action-list').replaceChildren();
 for(const a of state.actions.slice().reverse()){
 const box=node('section');box.append(node('h3',actionLabels[a.payload.kind]+' · '+a.payload.description),node('p',actionStates[a.status]));
 box.append(node('p','Исходная фраза: '+a.payload.evidence,'muted'));
 if(a.payload.amount_minor!==null)box.append(node('p',money(a.payload.amount_minor)));
 if(a.payload.starts_at)box.append(node('p',new Date(a.payload.starts_at).toLocaleString('ru-RU')));
 if(a.error)box.append(node('p',a.error));
 if(a.status!=='cancelled'){
 const cancel=node('button','Отменить действие','secondary');cancel.onclick=async()=>{try{await api(`/actions/${a.id}/cancel`,{method:'POST'});await loadActions();}catch(e){notice(e.message);}};box.append(cancel);
 }
 if(['needs_input','pending','waiting'].includes(a.status)&&!(a.payload.kind==='calendar'&&a.status==='waiting')){
 const edit=node('button','Уточнить','secondary');edit.onclick=()=>editAction(a);box.append(edit);
 }
 $('action-list').append(box);
 }
 } catch(e){notice(e.message);}
}
function editAction(a){
 const dialog=node('dialog'),form=node('form'), fields={};form.append(node('h2','Уточнить поручение'));
 function field(key,title,type='text',value=a.payload[key]){const label=node('label',title),input=node('input');input.type=type;input.value=value??'';label.append(input);form.append(label);fields[key]=input;return input;}
 field('description','Описание').required=true;
 if(a.payload.kind==='calendar'){
 field('starts_at','Дата и время (часовой пояс этого компьютера)','datetime-local','').required=true;
 field('duration_minutes','Длительность, минут','number',a.payload.duration_minutes??60).min=1;
 field('reminder_minutes','Напомнить за минут','number',a.payload.reminder_minutes??30).min=0;
 }else{
 const amount=field('amount','Сумма, ₸','number',(a.payload.amount_minor??0)/100);amount.step='0.01';amount.min='0.01';amount.required=true;
 field('category','Категория');
 if(a.payload.kind.startsWith('debt')){
 field('person','Человек').required=true;
 const label=node('label','Кто должен'),select=node('select');for(const [v,t] of [['i_owe','Я должен'],['owed_to_me','Мне должны']]){const o=node('option',t);o.value=v;select.append(o);}select.value=a.payload.direction??'i_owe';label.append(select);form.append(label);fields.direction=select;
 field('due_date','Срок возврата (необязательно)','date');
 const cash=field('cash_moved','В этой операции действительно передавались деньги','checkbox');cash.checked=a.payload.cash_moved;
 }
 }
 const save=node('button','Сохранить и выполнить');form.append(save);const close=node('button','Закрыть','secondary');close.type='button';close.onclick=()=>dialog.close();form.append(close);
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{
 const p={...a.payload,clarification:null};
 for(const [k,input] of Object.entries(fields)){
 if(k==='amount'){p.amount_minor=Math.round(Number(input.value)*100);p.currency='KZT';}
 else if(k==='cash_moved')p[k]=input.checked;
 else if(k==='starts_at')p[k]=new Date(input.value).toISOString();
 else if(k.endsWith('_minutes'))p[k]=Number(input.value);
 else p[k]=input.value||null;
 }
 await api(`/actions/${a.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});dialog.close();await loadActions();
 }catch(e){notice(e.message);}finally{save.disabled=false;}};
 dialog.append(form);document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();
}
$('finance-panel').ontoggle=()=>{if($('finance-panel').open)loadActions();};
$('actions-refresh').onclick=loadActions;
$('actions-retry').onclick=async()=>{try{await api('/actions/retry',{method:'POST'});await loadActions();}catch(e){notice(e.message);}};
$('budget-form').onsubmit=async e=>{e.preventDefault();try{await api('/budget',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({initial_minor:Math.round(Number($('budget-value').value)*100)})});await loadActions();}catch(e){notice(e.message);}};
$('google-json-button').onclick=()=>$('google-json').click();
$('google-json').onchange=async()=>{try{const f=$('google-json').files[0];if(!f)return;if(f.size>32000)throw Error('Слишком большой файл настроек');await api('/calendar/client',{method:'POST',headers:{'Content-Type':'application/json'},body:await f.text()});await loadActions();}catch(e){notice(e.message);}finally{$('google-json').value='';}};
$('google-connect').onclick=async()=>{try{const r=await(await api('/calendar/connect',{method:'POST'})).json();const link=node('a','Открыть вход Google');link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';$('calendar-state').replaceChildren(link);link.click();}catch(e){notice(e.message);}};

$('pair-addresses').onclick=async()=>{try{const data=await(await api('/pair/addresses')).json();$('pair-server').replaceChildren(...data.addresses.map(a=>{const o=node('option',a);o.value=a;return o;}));}catch(e){notice(e.message);}};
$('pair-create').onclick=async()=>{try{const data=await(await api('/pair/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({server:$('pair-server').value})})).json();$('pair-qr').src='data:image/svg+xml;base64,'+btoa(data.svg);$('pair-qr').hidden=false;setTimeout(()=>{$('pair-qr').hidden=true;$('pair-qr').removeAttribute('src');},data.expires_in*1000);}catch(e){notice(e.message);}};
function showUsage(data){$('usage-summary').textContent=data.notice+'\n\n'+data.rows.map(r=>`${r.model}: запросов ${r.requests}, без подтверждения ${r.unconfirmed}\nВход: ${r.input_tokens}, кэш: ${r.cached_tokens}, выход: ${r.output_tokens}, аудио: ${(r.audio_seconds/60).toFixed(2)} мин.\nОценка USD: ${r.estimated_usd===null?'тариф не задан':r.estimated_usd.toFixed(4)}`).join('\n\n');}
$('usage-refresh').onclick=async()=>{try{showUsage(await(await api('/usage')).json());}catch(e){notice(e.message);}};
$('price-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));for(const k of ['input','cached','output','audio_minute'])data[k]=Number(data[k]);try{showUsage(await(await api('/usage/prices',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json());}catch(e){notice(e.message);}};
