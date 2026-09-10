package local.jarvis.thoughts

import android.content.Context
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class UploadWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
    override fun doWork(): Result {
        val settings = SecureSettings(applicationContext)
        if (!SecureSettings.validServer(settings.server) || settings.token().isEmpty()) return Result.success()
        val store = LocalStore(applicationContext)
        val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()
        var retry = false
        store.use {
            for (row in store.all().filter { it.status in listOf("queued", "uploaded", "retry") }) {
                if (isStopped) return Result.retry()
                try {
                    val upload = row.status != "uploaded"
                    if (upload && !settings.autoSend && !inputData.getBoolean("manual", false)) continue
                    if (upload && !store.claim(row.id)) continue
                    val builder = Request.Builder().header("Authorization", "Bearer ${settings.token()}")
                    if (upload) {
                        val file = File(row.path)
                        if (!file.isFile) { store.update(row.id, "local_error", "Аудиофайл отсутствует"); continue }
                        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
                            .addFormDataPart("recording_id", row.id).addFormDataPart("captured_at", row.capturedAt)
                            .addFormDataPart("source", "android").addFormDataPart("device", "${Build.MANUFACTURER} ${Build.MODEL}".take(120))
                            .addFormDataPart("file", "${row.id}.wav", file.asRequestBody("audio/wav".toMediaType())).build()
                        builder.url("${settings.server}/recordings").post(body)
                    } else builder.url("${settings.server}/recordings/${row.id}")
                    client.newCall(builder.build()).execute().use { response ->
                        if (!response.isSuccessful) {
                            val temporary = response.code == 408 || response.code == 429 || response.code >= 500
                            store.update(row.id, if (temporary) (if (upload) "retry" else "uploaded") else "needs_attention", "Сервер: ${response.code}")
                            retry = retry || temporary
                            return@use
                        }
                        val json = response.body?.string() ?: throw IllegalStateException()
                        val result = JSONObject(json)
                        require(result.getString("id") == row.id)
                        if (upload) {
                            val digest = MessageDigest.getInstance("SHA-256")
                            File(row.path).inputStream().use { input ->
                                val buffer = ByteArray(65536)
                                var size = input.read(buffer)
                                while (size >= 0) { digest.update(buffer, 0, size); size = input.read(buffer) }
                            }
                            val expected = digest.digest().joinToString("") { "%02x".format(it) }
                            require(result.getString("sha256") == expected)
                        }
                        val serverStatus = result.getString("status")
                        val state = when (serverStatus) {
                            "saved" -> if (upload) "uploaded" else "saved"
                            "awaiting_ai" -> "awaiting_ai"
                            "failed" -> "server_error"
                            else -> "uploaded"
                        }
                        store.update(row.id, state, if (serverStatus == "failed") result.optString("error") else "", json)
                        if (state == "saved" || state == "awaiting_ai") notifySaved(row.id, state)
                        if (state == "uploaded") retry = true
                    }
                } catch (_: Exception) {
                    store.update(row.id, if (row.status == "uploaded") "uploaded" else "retry", "Нет подтверждения сервера. Аудио сохранено на телефоне.")
                    retry = true
                }
            }
            if (retry && runAttemptCount >= 7) {
                store.all().filter { it.status in listOf("queued", "uploaded", "retry") }.forEach {
                    store.update(it.id, "needs_attention", "Автоповторы исчерпаны. Нажмите «Отправить / обновить».")
                }
                return Result.failure()
            }
        }
        return if (retry) Result.retry() else Result.success()
    }
    private fun notifySaved(id: String, state: String) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("saved", "Сохранённые мысли", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(applicationContext, 0, Intent(applicationContext, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(id.hashCode(), NotificationCompat.Builder(applicationContext, "saved").setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(if (state == "saved") "Мысль сохранена" else "Расшифровка сохранена")
            .setContentText(if (state == "saved") "Откройте конспект и задачи" else "AI-конспект ожидает подключения ключа")
            .setContentIntent(open).setAutoCancel(true).build())
    }
    companion object {
        fun enqueue(context: Context, manual: Boolean = false) {
            if (manual) LocalStore(context).use { store ->
                store.all().filter { it.status in listOf("needs_attention", "server_error", "awaiting_ai", "saved") }.forEach { row ->
                    store.update(row.id, if (row.serverJson.isEmpty()) "retry" else "uploaded")
                }
            }
            val work = OneTimeWorkRequestBuilder<UploadWorker>()
                .setInputData(workDataOf("manual" to manual))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload", ExistingWorkPolicy.APPEND_OR_REPLACE, work)
        }
    }
}
