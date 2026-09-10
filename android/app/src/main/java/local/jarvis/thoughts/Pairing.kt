package local.jarvis.thoughts

import android.app.Activity
import android.app.AlertDialog
import android.widget.Toast
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object Pairing {
    private fun client() = OkHttpClient.Builder().callTimeout(15,TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()
    private fun message(a: Activity,t: String) = a.runOnUiThread { Toast.makeText(a,t,Toast.LENGTH_LONG).show() }
    fun check(a: Activity) {
        val s=SecureSettings(a)
        if (!SecureSettings.validServer(s.server)) { message(a,"Сначала укажите адрес компьютера"); return }
        Thread {
            try {
                client().newCall(Request.Builder().url(s.server+"/recordings?limit=1").header("Authorization","Bearer ${s.token()}").build()).execute().use {
                    message(a,when(it.code){200->"Связь и токен работают. Можно отправлять записи.";401->"Сервер доступен, но токен неверный. Подключитесь по QR заново.";else->"Сервер ответил с ошибкой. Проверьте приложение на ПК."})
                }
            } catch (_: Exception) { message(a,"Нет связи. Включите сервер на ПК и Tailscale либо подключитесь к домашней сети.") }
        }.start()
    }
    fun connect(a: Activity, text: String) {
        try {
            require(text.length<2048)
            val data=JSONObject(text)
            require(data.getString("type")=="friday-pair-v1")
            val url=data.getString("server");val code=data.getString("code")
            require(SecureSettings.validServer(url) && code.length in 24..100)
            AlertDialog.Builder(a).setTitle("Подключить к компьютеру?").setMessage(url+"\nТекущее подключение будет заменено после успешной проверки.")
                .setNegativeButton("Отмена",null).setPositiveButton("Подключить") { _, _ ->
                    Thread {
                        try {
                            val json=JSONObject().put("code",code).toString().toRequestBody("application/json".toMediaType())
                            client().newCall(Request.Builder().url(url+"/pair/claim").post(json).build()).execute().use {
                                if (!it.isSuccessful) { message(a,"Код истёк, использован или сервер недоступен. Создайте новый QR."); return@Thread }
                                val result=JSONObject(it.body!!.string());require(result.getString("service")=="jarvis-thoughts")
                                val token=result.getString("token");require(token.length>=24)
                                val settings=SecureSettings(a);settings.saveToken(token);settings.server=url
                            }
                            message(a,"Телефон подключён. Проверяем связь.");check(a)
                        } catch (_: Exception) { message(a,"Не удалось подключиться. Создайте новый QR и проверьте сеть.") }
                    }.start()
                }.show()
        } catch (_: Exception) { message(a,"Это не QR подключения Джарвиса") }
    }
}
