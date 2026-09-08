package local.jarvis.thoughts

import android.content.Context
import android.os.Build
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
                            store.update(row.id, if (temporary) row.status else "needs_attention", "Сервер: ${response.code}")
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
                            "saved" -> "saved"
                            "awaiting_ai" -> "awaiting_ai"
                            "failed" -> "server_error"
                            else -> "uploaded"
                        }
                        store.update(row.id, state, if (serverStatus == "failed") result.optString("error") else "", json)
                        if (state == "uploaded") retry = true
                    }
                } catch (_: Exception) {
                    store.update(row.id, row.status, "Нет подтверждения сервера. Аудио сохранено на телефоне.")
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
    companion object {
        fun enqueue(context: Context, manual: Boolean = false) {
            if (manual) LocalStore(context).use { store ->
                store.all().filter { it.status in listOf("needs_attention", "server_error", "awaiting_ai") }.forEach { row ->
                    store.update(row.id, if (row.serverJson.isEmpty()) "queued" else "uploaded")
                }
            }
            val work = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload", ExistingWorkPolicy.APPEND_OR_REPLACE, work)
        }
    }
}
