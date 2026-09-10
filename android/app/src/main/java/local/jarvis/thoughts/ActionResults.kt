package local.jarvis.thoughts

import android.app.Activity
import android.app.AlertDialog
import android.widget.*
import okhttp3.*
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object ActionResults {
    fun show(activity: Activity, recordingId: String) {
        val settings = SecureSettings(activity)
        val client = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()
        fun request(path: String) = Request.Builder().url(settings.server + path).header("Authorization", "Bearer ${settings.token()}")
        fun message(value: String) = activity.runOnUiThread { Toast.makeText(activity,value,Toast.LENGTH_LONG).show() }
        Thread {
            try {
                val array = client.newCall(request("/actions").build()).execute().use {
                    check(it.isSuccessful); JSONObject(it.body!!.string()).getJSONArray("actions")
                }
                val rows = (0 until array.length()).map { array.getJSONObject(it) }.filter { it.getString("recording_id") == recordingId }
                activity.runOnUiThread {
                    if (activity.isFinishing) return@runOnUiThread
                    val box = LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL; setPadding(24,16,24,16) }
                    if (rows.isEmpty()) box.addView(TextView(activity).apply { text="Поручений нет или обработка ещё продолжается." })
                    rows.forEach { row ->
                        val payload = row.getJSONObject("payload")
                        val label = payload.getString("description") + if (!payload.isNull("amount_minor")) " — ${payload.getLong("amount_minor")/100.0} ₸" else ""
                        val state = mapOf("applied" to "Выполнено", "cancelled" to "Отменено", "pending" to "В очереди", "waiting" to "Ожидает", "needs_input" to "Нужно уточнение")[row.getString("status")] ?: row.getString("status")
                        box.addView(TextView(activity).apply { text=label+"\n"+state+if (!row.isNull("error")) "\n"+row.getString("error") else ""; textSize=17f })
                        if (row.getString("status") in listOf("needs_input","waiting","pending")) box.addView(Button(activity).apply {
                            text="Уточнить";setOnClickListener { ClarifyAction.show(activity,row,recordingId) }
                        })
                        if (row.getString("status") != "cancelled") box.addView(Button(activity).apply {
                            text="Отменить действие"
                            setOnClickListener {
                                val effect = if (payload.getString("kind")=="calendar") "Созданная встреча будет удалена из Google Календаря." else "Операция будет отменена в учёте. Баланс и долги пересчитаются. Банковского перевода не будет."
                                AlertDialog.Builder(activity).setTitle(label).setMessage(effect).setNegativeButton("Оставить",null)
                                    .setPositiveButton("Отменить действие") { _, _ ->
                                        Thread {
                                            try {
                                                client.newCall(request("/actions/${row.getString("id")}/cancel").post(ByteArray(0).toRequestBody()).build()).execute().use {
                                                    if (!it.isSuccessful) { message("Отмена не выполнена. Для долга сначала отмените погашения; подробности — в Джарвисе на ПК."); return@Thread }
                                                }
                                                message("Действие отменено")
                                                activity.runOnUiThread { show(activity,recordingId) }
                                            } catch (_: Exception) { message("Нет подтверждения отмены. Обновите результат, когда сервер станет доступен.") }
                                        }.start()
                                    }.show()
                            }
                        })
                    }
                    AlertDialog.Builder(activity).setTitle("Результат поручений").setView(ScrollView(activity).apply { addView(box) }).setPositiveButton("Закрыть",null).show()
                }
            } catch (_: Exception) { message("Не удалось получить результат. Проверьте сервер и подключение.") }
        }.start()
    }
}
