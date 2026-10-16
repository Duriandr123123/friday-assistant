package local.jarvis.thoughts

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.util.Linkify
import android.widget.*
import androidx.work.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import android.Manifest
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.core.content.ContextCompat
import java.io.File
import okhttp3.RequestBody.Companion.asRequestBody

class ChatState(context: Context) {
    private val prefs=context.getSharedPreferences("assistant",Context.MODE_PRIVATE)
    var enabled: Boolean
        get()=prefs.getBoolean("enabled",true)
        set(value) { prefs.edit().putBoolean("enabled",value).commit() }
    fun conversation(): String = synchronized(lock) {
        prefs.getString("conversation",null) ?: UUID.randomUUID().toString().also { select(it) }
    }
    fun select(id: String) { UUID.fromString(id); prefs.edit().putString("conversation",id).commit() }
    fun newConversation() { select(UUID.randomUUID().toString()) }
    fun pending(): JSONArray = synchronized(lock) { JSONArray(prefs.getString("outbox","[]")) }
    fun add(text: String) = synchronized(lock) {
        val row=JSONObject().put("id",UUID.randomUUID().toString()).put("conversation_id",conversation()).put("text",text)
        val all=pending(); all.put(row); prefs.edit().putString("outbox",all.toString()).commit()
    }
    fun sent(id: String) = synchronized(lock) {
        val all=pending(); val keep=JSONArray()
        for(i in 0 until all.length()) if(all.getJSONObject(i).getString("id")!=id) keep.put(all.getJSONObject(i))
        prefs.edit().putString("outbox",keep.toString()).commit()
    }
    fun cached(id: String)=JSONArray(prefs.getString("chat:$id","[]"))
    fun cache(id: String, rows: JSONArray) { prefs.edit().putString("chat:$id",rows.toString()).commit() }
    companion object { private val lock=Any() }
}

object ChatNetwork {
    private val client=OkHttpClient.Builder().connectTimeout(15,TimeUnit.SECONDS).readTimeout(40,TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()
    fun request(context: Context,path: String,body: JSONObject?=null,delete: Boolean=false): String {
        val settings=SecureSettings(context)
        require(SecureSettings.validServer(settings.server) && settings.token().isNotEmpty()) { "Настройте подключение к ПК" }
        val req=Request.Builder().url(settings.server+path).header("Authorization","Bearer ${settings.token()}")
        if(body!=null) req.post(body.toString().toRequestBody("application/json".toMediaType()))
        if(delete) req.delete()
        return client.newCall(req.build()).execute().use {
            check(it.isSuccessful) { if(it.code==401) "Проверьте токен" else "Сервер: ${it.code}" }
            it.body?.string() ?: "{}"
        }
    }
    fun sync(context: Context): Boolean {
        val state=ChatState(context); val pending=state.pending()
        for(i in 0 until pending.length()) { val row=pending.getJSONObject(i)
            request(context,"/assistant/messages",row); state.sent(row.getString("id"))
        }
        val cid=state.conversation()
        val rows=JSONArray(request(context,"/assistant/turns?conversation_id=$cid")); state.cache(cid,rows)
        return (0 until rows.length()).any { rows.getJSONObject(it).optString("status") in listOf("queued","running") }
    }
    fun upload(context: Context,file: File,name: String): JSONObject {
        val s=SecureSettings(context)
        require(SecureSettings.validServer(s.server) && s.token().isNotEmpty())
        val body=MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file",name,file.asRequestBody("application/octet-stream".toMediaType())).build()
        return client.newCall(Request.Builder().url(s.server+"/assistant/files").header("Authorization","Bearer ${s.token()}").post(body).build()).execute().use {
            check(it.isSuccessful) { "Загрузка: ${it.code}. Поддерживаются PDF, DOCX, XLSX, PPTX, TXT, MD, CSV до 20 МБ." }
            JSONObject(it.body!!.string())
        }
    }
}

class ChatWorker(context: Context,params: WorkerParameters): Worker(context,params) {
    override fun doWork(): Result = try {
        if(ChatNetwork.sync(applicationContext) && runAttemptCount<12) Result.retry() else Result.success()
    } catch(_: Exception) { if(runAttemptCount<12) Result.retry() else Result.failure() }
    companion object {
        fun enqueue(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork("assistant-chat",ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<ChatWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,10,TimeUnit.SECONDS).build())
        }
    }
}

class AssistantChatActivity: Activity() {
    private lateinit var list: LinearLayout
    private lateinit var status: TextView
    private lateinit var input: EditText
    private lateinit var state: ChatState
    private val handler=Handler(Looper.getMainLooper())
    private val busy=AtomicBoolean(false)
    private var visible=false
    private var snapshot=""
    private fun dp(v: Int)=(v*resources.displayMetrics.density).toInt()
    private fun label(s: String,size: Float=16f)=TextView(this).apply {
        text=s; textSize=size; setTextColor(Color.WHITE); setPadding(dp(12),dp(10),dp(12),dp(10))
    }
    private fun button(s: String,action: ()->Unit)=Button(this).apply { text=s; isAllCaps=false; setOnClickListener { action() } }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); state=ChatState(this)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(12),dp(24),dp(12),dp(12)); setBackgroundColor(Color.rgb(12,21,31)) }
        root.addView(label("ПЯТНИЦА · личный помощник",23f))
        status=label("История хранится на вашем ПК",13f); root.addView(status)
        val actions=LinearLayout(this)
        actions.addView(button("Новый диалог") { state.newConversation(); snapshot=""; render(); fetch() },LinearLayout.LayoutParams(0,-2,1f))
        actions.addView(button("История") { history() },LinearLayout.LayoutParams(0,-2,1f))
        actions.addView(button("Память") { memory() },LinearLayout.LayoutParams(0,-2,1f)); root.addView(actions)
        val extras=LinearLayout(this)
        extras.addView(button("Прикрепить файл") { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE),41) },LinearLayout.LayoutParams(0,-2,1f))
        extras.addView(button("Моё местоположение") { location() },LinearLayout.LayoutParams(0,-2,1f)); root.addView(extras)
        val scroll=ScrollView(this); list=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }; scroll.addView(list)
        root.addView(scroll,LinearLayout.LayoutParams(-1,0,1f))
        input=EditText(this).apply { hint="Что нужно сделать?"; setHintTextColor(Color.LTGRAY); setTextColor(Color.WHITE); minLines=2; maxLines=5 }; root.addView(input)
        val send=LinearLayout(this)
        send.addView(button("Отправить") {
            val value=input.text.toString().trim()
            if(value.isNotEmpty() && value.length<=16000) { state.add(value); input.setText(""); snapshot=""; render(); ChatWorker.enqueue(this); fetch() }
        },LinearLayout.LayoutParams(0,-2,1f))
        send.addView(button("Голосом") { state.enabled=true; startActivity(Intent(this,MainActivity::class.java).setAction("local.jarvis.RECORD")) },LinearLayout.LayoutParams(0,-2,1f))
        send.addView(button("Обновить") { fetch(); ChatWorker.enqueue(this) },LinearLayout.LayoutParams(0,-2,1f)); root.addView(send)
        setContentView(root); render()
    }
    private val poll=object: Runnable { override fun run() { if(visible) { fetch(); handler.postDelayed(this,3000) } } }
    override fun onResume() { super.onResume(); visible=true; handler.post(poll) }
    override fun onPause() { visible=false; handler.removeCallbacks(poll); super.onPause() }
    private fun fetch() {
        if(!busy.compareAndSet(false,true)) return
        Thread {
            var error: String?=null
            try { ChatNetwork.sync(this) } catch(e: Exception) { error=e.message ?: "ПК недоступен" }
            runOnUiThread { busy.set(false); if(!isFinishing) {
                status.text=if(error==null) "На связи · выполняю на ПК" else "$error. Сообщения сохранены, повторим отправку."; render()
            } }
        }.start()
    }
    private fun act(path: String,body: JSONObject=JSONObject()) {
        Thread { try { ChatNetwork.request(this,path,body); runOnUiThread { fetch() } }
            catch(e: Exception) { runOnUiThread { Toast.makeText(this,e.message,Toast.LENGTH_LONG).show() } }
        }.start()
    }
    private fun render() {
        val cid=state.conversation(); val rows=state.cached(cid); val pending=state.pending(); val key=rows.toString()+pending.toString()+cid
        if(snapshot==key) return
        snapshot=key; list.removeAllViews()
        if(rows.length()==0) list.addView(label("Поручите задачу или задайте вопрос. Доступны поиск в интернете, заметки, бюджет и подключённый календарь. Для продолжения отвечайте в этом диалоге.",15f))
        val statuses=mapOf("queued" to "В очереди","running" to "Работаю","waiting_approval" to "Нужно подтверждение","completed" to "Ответ готов","error" to "Ошибка","paused" to "Можно продолжить","cancelled" to "Остановлено")
        val known=mutableSetOf<String>()
        for(i in 0 until rows.length()) {
            val row=rows.getJSONObject(i); val id=row.getString("id"); known.add(id)
            list.addView(label("Вы: "+row.getString("text")).apply { setBackgroundColor(Color.rgb(29,54,66)) })
            if(row.optString("response").isNotBlank()) list.addView(label(row.optString("response")).apply {
                autoLinkMask=Linkify.WEB_URLS; movementMethod=android.text.method.LinkMovementMethod.getInstance(); setTextIsSelectable(true)
            })
            val stage=row.optString("status"); val events=row.optJSONArray("events")
            val latest=if(events!=null && events.length()>0) events.getJSONObject(events.length()-1).optString("text") else ""
            list.addView(label((statuses[stage] ?: stage)+(if(stage=="running") " · $latest" else ""),12f))
            val receipts=row.optJSONArray("receipts") ?: JSONArray()
            for(j in 0 until receipts.length()) { val receipt=receipts.getJSONObject(j)
                val actionStatus=mapOf("applied" to "Выполнено","approval" to "Ждёт подтверждения","cancelled" to "Отменено","needs_input" to "Нужно уточнение","waiting" to "Ожидает")[receipt.optString("status")] ?: receipt.optString("status")
                val amount=if(receipt.isNull("amount_tenge")) "" else " · "+receipt.optString("amount_tenge")+" ₸"
                list.addView(label("Учёт: "+receipt.optString("description")+amount+" · "+actionStatus,14f).apply { setBackgroundColor(Color.rgb(20,65,54)) })
            }
            if(!row.isNull("current_balance_tenge")) list.addView(label("Текущий остаток по учёту: "+row.optString("current_balance_tenge")+" ₸",14f))
            val sources=row.optJSONArray("citations") ?: JSONArray()
            for(j in 0 until sources.length()) { val source=sources.getJSONObject(j); val url=source.optString("url")
                if(url.startsWith("https://") || url.startsWith("http://")) list.addView(button("Источник: "+source.optString("title")) {
                    try { startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(url))) } catch(_: Exception) { }
                })
            }
            val approvals=row.optJSONArray("approvals") ?: JSONArray()
            for(j in 0 until approvals.length()) { val a=approvals.getJSONObject(j)
                val description=a.optString("description")+"\n"+(a.optJSONObject("details")?.optString("starts_at") ?: "")
                list.addView(button("Подтвердить: "+a.optString("description")) {
                    AlertDialog.Builder(this).setTitle("Выполнить действие?").setMessage(description)
                        .setPositiveButton("Выполнить") { _,_-> act("/assistant/approvals/${a.getString("id")}",JSONObject().put("approved",true)) }
                        .setNegativeButton("Отклонить") { _,_-> act("/assistant/approvals/${a.getString("id")}",JSONObject().put("approved",false)) }.show()
                })
            }
            if(stage in listOf("paused","error")) list.addView(button("Продолжить") { act("/assistant/turns/$id/continue") })
            if(stage in listOf("queued","running","paused","waiting_approval")) list.addView(button("Остановить задачу") { act("/assistant/turns/$id/cancel") })
        }
        for(i in 0 until pending.length()) { val row=pending.getJSONObject(i)
            if(row.getString("conversation_id")==cid && row.getString("id") !in known) list.addView(label("Ожидает отправки: "+row.getString("text")))
        }
    }
    private fun history() {
        Thread { try {
            val rows=JSONArray(ChatNetwork.request(this,"/assistant/turns")); val ids=mutableListOf<String>(); val labels=mutableListOf<String>()
            for(i in rows.length()-1 downTo 0) { val r=rows.getJSONObject(i); val cid=r.getString("conversation_id")
                if(cid !in ids) { ids.add(cid); labels.add(r.optString("text").take(70)) }
            }
            runOnUiThread { AlertDialog.Builder(this).setTitle("Диалоги").setItems(labels.toTypedArray()) { _,i-> state.select(ids[i]); snapshot=""; render(); fetch() }.setNegativeButton("Закрыть",null).show() }
        } catch(e: Exception) { runOnUiThread { Toast.makeText(this,e.message,Toast.LENGTH_LONG).show() } } }.start()
    }
    private fun memory() {
        Thread { try {
            val rows=JSONArray(ChatNetwork.request(this,"/assistant/memory"))
            val labels=(0 until rows.length()).map { val r=rows.getJSONObject(it); r.getString("key")+": "+r.getString("value") }
            runOnUiThread { AlertDialog.Builder(this).setTitle("Память · нажмите, чтобы забыть").setItems(labels.toTypedArray()) { _,i->
                val r=rows.getJSONObject(i)
                AlertDialog.Builder(this).setMessage("Забыть: "+r.getString("value")+"?").setPositiveButton("Забыть") { _,_->
                    Thread { try { ChatNetwork.request(this,"/assistant/memory/"+Uri.encode(r.getString("key")),delete=true); runOnUiThread { memory() } }
                        catch(e: Exception) { runOnUiThread { Toast.makeText(this,e.message,Toast.LENGTH_LONG).show() } } }.start()
                }.setNegativeButton("Оставить",null).show()
            }.setNegativeButton("Закрыть",null).show() }
        } catch(e: Exception) { runOnUiThread { Toast.makeText(this,e.message,Toast.LENGTH_LONG).show() } } }.start()
    }
    private fun location() {
        if(ContextCompat.checkSelfPermission(this,Manifest.permission.ACCESS_COARSE_LOCATION)!=PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION),42); return
        }
        try {
            val manager=getSystemService(LocationManager::class.java)
            val consume: (android.location.Location?)->Unit = { loc ->
                if(loc==null || System.currentTimeMillis()-loc.time>10*60*1000) Toast.makeText(this,"Свежая позиция недоступна. Включите геолокацию или укажите район текстом.",Toast.LENGTH_LONG).show()
                else { state.add("Моя приблизительная позиция сейчас: широта ${loc.latitude}, долгота ${loc.longitude}, погрешность ${loc.accuracy.toInt()} м. Учти её для текущего поиска, не сохраняй как постоянный адрес."); ChatWorker.enqueue(this); fetch() }
            }
            if(android.os.Build.VERSION.SDK_INT>=30) {
                val signal=android.os.CancellationSignal(); handler.postDelayed({ signal.cancel() },20000)
                manager.getCurrentLocation(LocationManager.NETWORK_PROVIDER,signal,mainExecutor) { consume(it) }
            } else consume(manager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER))
        } catch(_: Exception) { Toast.makeText(this,"Не удалось получить позицию. Укажите город или район сообщением.",Toast.LENGTH_LONG).show() }
    }
    override fun onRequestPermissionsResult(code: Int,permissions: Array<out String>,results: IntArray) {
        super.onRequestPermissionsResult(code,permissions,results)
        if(code==42 && results.firstOrNull()==PackageManager.PERMISSION_GRANTED) location()
    }
    override fun onActivityResult(code: Int,result: Int,data: Intent?) {
        super.onActivityResult(code,result,data)
        if(code!=41 || result!=RESULT_OK || data?.data==null) return
        val uri=data.data!!; val task=input.text.toString().trim().ifEmpty { "Проанализируй файл и кратко изложи главное." }; input.setText("")
        status.text="Загружаю файл…"
        Thread {
            val temp=File.createTempFile("attachment-",".upload",cacheDir)
            try {
                var name="document.txt"
                contentResolver.query(uri,arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),null,null,null)?.use { c -> if(c.moveToFirst()) name=c.getString(0) }
                contentResolver.openInputStream(uri)!!.use { stream -> temp.outputStream().use { output ->
                    val buf=ByteArray(65536); var total=0; var n=stream.read(buf)
                    while(n>=0) { total+=n; require(total<=20*1024*1024) { "Максимум 20 МБ" }; output.write(buf,0,n); n=stream.read(buf) }
                } }
                val file=ChatNetwork.upload(this,temp,name)
                state.add(task+"\nЗагруженный файл: "+file.getString("name")+"; file_id="+file.getString("file_id"))
                ChatWorker.enqueue(this); runOnUiThread { snapshot=""; render(); fetch() }
            } catch(e: Exception) { runOnUiThread { input.setText(task); status.text=e.message ?: "Ошибка загрузки" } }
            finally { temp.delete() }
        }.start()
    }
}
