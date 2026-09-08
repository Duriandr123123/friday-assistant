package local.jarvis.thoughts

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.MediaPlayer
import android.os.*
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.*
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.io.File

class MainActivity : Activity() {
    private lateinit var state: TextView
    private lateinit var list: LinearLayout
    private lateinit var record: Button
    private val handler = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var lastSnapshot = ""
    private var pendingRecord = false
    private val refresh = object : Runnable {
        override fun run() { refreshRows(); handler.postDelayed(this, 1500) }
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun text(value: String, size: Float = 16f) = TextView(this).apply {
        text = value; textSize = size; setTextColor(Color.WHITE); setPadding(0, dp(8), 0, dp(8))
    }
    private fun button(value: String, action: () -> Unit) = Button(this).apply {
        text = value; isAllCaps = false; setOnClickListener { action() }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(12, 21, 31)
        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(30), dp(22), dp(30)); setBackgroundColor(Color.rgb(12, 21, 31))
        }
        root.setOnApplyWindowInsetsListener { v, insets ->
            v.setPadding(dp(22), dp(16) + insets.systemWindowInsetTop, dp(22), dp(16) + insets.systemWindowInsetBottom)
            insets
        }
        root.addView(text("ДЖАРВИС", 28f))
        root.addView(text("Ваши мысли — под рукой", 16f))
        state = text("Готов", 20f); root.addView(state)
        record = button("Записать мысль") {
            if (RecordingService.active) startService(Intent(this, RecordingService::class.java).setAction(RecordingService.STOP))
            else beginRecording()
        }.apply { minHeight = dp(100); textSize = 22f; setTextColor(Color.BLACK); setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(51, 216, 197))) }
        root.addView(record)
        root.addView(button("Подключение и микрофон") { settingsDialog() })
        root.addView(button("Отправить / обновить") { UploadWorker.enqueue(this, manual = true); toast("Очередь запущена") })
        root.addView(text("Записи на телефоне", 22f))
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }; root.addView(list)
        scroll.addView(root); setContentView(scroll)
        if (intent.action == "local.jarvis.RECORD") { pendingRecord = true; intent.action = null }
    }
    override fun onResume() {
        super.onResume(); handler.post(refresh)
        if (pendingRecord) { pendingRecord = false; beginRecording() }
    }
    override fun onPause() { handler.removeCallbacks(refresh); super.onPause() }
    override fun onDestroy() { player?.release(); super.onDestroy() }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == "local.jarvis.RECORD" && !RecordingService.active) beginRecording()
    }
    private fun toast(value: String) = Toast.makeText(this, value, Toast.LENGTH_LONG).show()
    private fun beginRecording() {
        if (RecordingService.active) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 10); return
        }
        try { ContextCompat.startForegroundService(this, Intent(this, RecordingService::class.java)) }
        catch (_: Exception) { toast("Не удалось начать запись. Откройте приложение и повторите.") }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        if (requestCode == 10 && results.firstOrNull() == PackageManager.PERMISSION_GRANTED) beginRecording()
        else if (requestCode == 10) toast("Для записи разрешите микрофон в настройках приложения")
    }
    private fun settingsDialog() {
        val settings = SecureSettings(this)
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(8), dp(18), dp(8)) }
        val url = EditText(this).apply { hint = "http://192.168.1.10:8765"; setText(settings.server); inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI }
        val token = EditText(this).apply { hint = "Токен из connection.txt"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        val bluetooth = CheckBox(this).apply { text = "Использовать гарнитуру, если доступна"; isChecked = settings.bluetooth }
        val silence = CheckBox(this).apply { text = "Останавливать после 5 секунд тишины (экспериментально)"; isChecked = settings.silenceSeconds > 0 }
        box.addView(text("Адрес компьютера")); box.addView(url); box.addView(token)
        box.addView(text("Оставьте токен пустым, чтобы сохранить текущий. Без подключения запись остаётся на телефоне.", 14f))
        box.addView(bluetooth); box.addView(silence)
        val dialog = AlertDialog.Builder(this).setTitle("Подключение").setView(box).setPositiveButton("Сохранить", null)
            .setNegativeButton("Отмена", null).create()
        dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val value = url.text.toString().trim().trimEnd('/')
                if (!SecureSettings.validServer(value)) { url.error = "Нужен HTTPS-адрес или HTTP с локальным IP"; return@setOnClickListener }
                val secret = token.text.toString().trim()
                if (secret.isNotEmpty() && secret.length < 24) { token.error = "Токен должен содержать минимум 24 символа"; return@setOnClickListener }
                settings.server = value; settings.bluetooth = bluetooth.isChecked; settings.silenceSeconds = if (silence.isChecked) 5 else 0
                if (secret.isNotEmpty()) settings.saveToken(secret)
                val permissions = mutableListOf<String>()
                if (Build.VERSION.SDK_INT >= 31 && bluetooth.isChecked) permissions += Manifest.permission.BLUETOOTH_CONNECT
                if (Build.VERSION.SDK_INT >= 33) permissions += Manifest.permission.POST_NOTIFICATIONS
                val missing = permissions.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
                if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 20)
                UploadWorker.enqueue(this, manual = true); dialog.dismiss()
            }
        }
        dialog.show()
    }
    private val statuses = mapOf("recording" to "Слушаю", "queued" to "В очереди", "retry" to "Повтор отправки",
        "uploaded" to "Обрабатывается на ПК", "saved" to "Сохранено", "awaiting_ai" to "Расшифровано · ожидает AI",
        "server_error" to "Ошибка обработки на ПК", "needs_attention" to "Нужно повторить отправку", "local_error" to "Ошибка записи")
    private fun refreshRows() {
        record.text = if (RecordingService.active) "Остановить запись" else "Записать мысль"
        val rows = LocalStore(this).use { it.all() }
        state.text = if (RecordingService.active) RecordingService.message
            else rows.firstOrNull()?.let { statuses[it.status] } ?: RecordingService.message
        val snapshot = rows.toString()
        if (snapshot == lastSnapshot) return
        lastSnapshot = snapshot; list.removeAllViews()
        if (rows.isEmpty()) { list.addView(text("Пока нет записей. Нажмите кнопку и скажите первую мысль.")); return }
        rows.take(100).forEach { row ->
            val title = try { JSONObject(row.serverJson).optJSONObject("result")?.optString("title") } catch (_: Exception) { null }
            val label = "${title ?: row.capturedAt.take(16).replace('T', ' ')}\n${statuses[row.status] ?: row.status}"
            list.addView(button(label) { showRecording(row) })
        }
    }
    private fun showRecording(row: LocalRecording) {
        val server = try { JSONObject(row.serverJson) } catch (_: Exception) { JSONObject() }
        val result = server.optJSONObject("result")
        val body = buildString {
            append(statuses[row.status] ?: row.status); append("\n\n")
            if (row.error.isNotBlank()) append(row.error + "\n\n")
            if (result != null) {
                append(result.optString("summary") + "\n\n")
                val tasks = result.optJSONArray("tasks")
                if (tasks != null) for (i in 0 until tasks.length()) {
                    val task = tasks.getJSONObject(i)
                    append("• " + task.getString("text"))
                    if (!task.isNull("deadline")) append(" — " + task.getString("deadline"))
                    append("\n")
                }
            }
            if (!server.isNull("raw_transcript")) append("\nИсходная расшифровка\n" + server.optString("raw_transcript"))
            append("\n\nАудио хранится на телефоне.")
        }
        val scroll = ScrollView(this).apply { addView(text(body).apply { setPadding(dp(20), dp(8), dp(20), dp(8)) }) }
        AlertDialog.Builder(this).setTitle(result?.optString("title") ?: "Запись мысли").setView(scroll)
            .setPositiveButton("Закрыть") { _, _ -> player?.release(); player = null }
            .setNeutralButton("Прослушать") { _, _ ->
                try {
                    player?.release()
                    player = MediaPlayer().apply { setDataSource(row.path); prepare(); start(); setOnCompletionListener { it.release(); player = null } }
                } catch (_: Exception) { toast("Аудио недоступно") }
            }.show()
    }
}
