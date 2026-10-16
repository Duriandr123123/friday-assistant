/* Uses the existing authenticated API helper; all model content is rendered as text. */
(() => {
 let conversation=localStorage.getItem('friday-conversation') || crypto.randomUUID();
 localStorage.setItem('friday-conversation',conversation);
 let busy=false, fingerprint='';
 const labels={queued:'В очереди',running:'Работаю',completed:'Ответ готов',waiting_approval:'Нужно подтверждение',error:'Ошибка обработки',paused:'Можно продолжить',cancelled:'Остановлено'};
 const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const get=id=>document.getElementById(id);
 const json=async(path,body)=> (await api(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
 const button=(root,label,action)=>{const b=make('button',label);b.type='button';b.onclick=()=>Promise.resolve(action()).catch(e=>get('chat-state').textContent=e.message);root.append(b);};
 async function refresh(){
  if(busy || get('workspace').hidden)return;
  busy=true;
  try{
   const outbox=JSON.parse(localStorage.getItem('friday-outbox')||'[]');
   for(const row of outbox){await json('/assistant/messages',row);const current=JSON.parse(localStorage.getItem('friday-outbox')||'[]');localStorage.setItem('friday-outbox',JSON.stringify(current.filter(r=>r.id!==row.id)));}
   const rows=await json('/assistant/turns?conversation_id='+encodeURIComponent(conversation));
   get('chat-state').textContent='На связи · '+rows.length+' сообщений';
   const next=JSON.stringify(rows)+conversation;if(next===fingerprint)return;fingerprint=next;
   const box=get('chat-messages');box.replaceChildren();
   for(const row of rows){
    const card=make('article');card.append(make('h3','Вы: '+row.text),make('p',row.response||labels[row.status]||row.status));
    card.lastChild.style.whiteSpace='pre-wrap';
    card.append(make('small',(labels[row.status]||row.status)+(row.status==='running'?' · '+(row.events.at(-1)?.text||''):'')));
    for(const a of row.receipts||[])card.append(make('p','Учёт: '+a.description+(a.amount_tenge?' · '+a.amount_tenge+' ₸':'')+' · '+({applied:'Выполнено',approval:'Ждёт подтверждения',cancelled:'Отменено',needs_input:'Нужно уточнение',waiting:'Ожидает'}[a.status]||a.status)));
    if(row.current_balance_tenge!==null)card.append(make('p','Текущий остаток по учёту: '+row.current_balance_tenge+' ₸'));
    for(const source of row.citations||[]){try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))continue;const link=make('a',source.title||'Источник');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';const p=make('p');p.append(link);card.append(p);}catch{}}
    for(const a of row.approvals||[]){
     const preview=a.description+(a.details.starts_at?' · '+new Date(a.details.starts_at).toLocaleString('ru-RU')+' · '+a.details.duration_minutes+' мин.':'');
     card.append(make('p','Подтверждение: '+preview));
     button(card,'Подтвердить',async()=>{if(confirm('Выполнить: '+preview+'?')){await json('/assistant/approvals/'+a.id,{approved:true});await refresh();}});
     button(card,'Отклонить',async()=>{await json('/assistant/approvals/'+a.id,{approved:false});await refresh();});
    }
    if(['error','paused'].includes(row.status))button(card,'Продолжить',async()=>{await json('/assistant/turns/'+row.id+'/continue',{});await refresh();});
    if(['running','queued','paused','waiting_approval'].includes(row.status))button(card,'Остановить',async()=>{await json('/assistant/turns/'+row.id+'/cancel',{});await refresh();});
    box.append(card);
   }
  }catch(e){get('chat-state').textContent=e.message+' · неотправленные сообщения сохранены в браузере';}
  finally{busy=false;}
 }
 get('chat-form').onsubmit=async e=>{e.preventDefault();const text=get('chat-input').value.trim();if(!text)return;
  const outbox=JSON.parse(localStorage.getItem('friday-outbox')||'[]');outbox.push({id:crypto.randomUUID(),conversation_id:conversation,text});
  localStorage.setItem('friday-outbox',JSON.stringify(outbox));get('chat-input').value='';get('chat-state').textContent='Отправляю…';await refresh();};
 get('chat-new').onclick=()=>{conversation=crypto.randomUUID();localStorage.setItem('friday-conversation',conversation);fingerprint='';refresh();};
 get('chat-refresh').onclick=refresh;
 get('chat-history').onclick=async()=>{try{const rows=await json('/assistant/turns');const seen=new Set();const box=get('chat-messages');box.replaceChildren();
  for(const row of rows.reverse())if(!seen.has(row.conversation_id)){seen.add(row.conversation_id);button(box,row.text.slice(0,100),()=>{conversation=row.conversation_id;localStorage.setItem('friday-conversation',conversation);fingerprint='';refresh();});}
 }catch(e){get('chat-state').textContent=e.message;}};
 get('chat-memory').onclick=async()=>{try{const rows=await json('/assistant/memory');const box=get('chat-messages');box.replaceChildren();fingerprint='memory';
  if(!rows.length)box.append(make('p','Сохранённых фактов пока нет.'));
  for(const r of rows){const card=make('article');card.append(make('p',r.key+': '+r.value));button(card,'Забыть',async()=>{if(confirm('Забыть этот факт?')){await api('/assistant/memory/'+encodeURIComponent(r.key),{method:'DELETE'});get('chat-memory').click();}});box.append(card);}
 }catch(e){get('chat-state').textContent=e.message;}};
 setInterval(()=>{if(get('assistant-panel').open && fingerprint!=='memory')refresh();},4000);
})();
