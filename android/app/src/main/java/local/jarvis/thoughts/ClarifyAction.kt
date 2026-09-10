package local.jarvis.thoughts

import android.app.Activity
import android.app.AlertDialog
import android.widget.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.math.BigDecimal
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

object ClarifyAction {
    fun show(a:Activity,row:JSONObject,recordingId:String) {
        val payload=JSONObject(row.getJSONObject("payload").toString())
        val box=LinearLayout(a).apply { orientation=LinearLayout.VERTICAL;setPadding(24,12,24,12) }
        fun field(label:String,value:String):EditText {
            box.addView(TextView(a).apply {text=label})
            return EditText(a).apply {setText(value);box.addView(this)}
        }
        val description=field("Что сделать",payload.getString("description"))
        val kind=payload.getString("kind")
        val amount=if(kind!="calendar")field("Сумма в тенге",if(payload.isNull("amount_minor"))"" else BigDecimal(payload.getLong("amount_minor")).movePointLeft(2).toPlainString()) else null
        val person=if(kind.startsWith("debt"))field("Имя человека",payload.optString("person","").replace("null","")) else null
        val direction=if(kind.startsWith("debt")) Spinner(a).apply {
            adapter=ArrayAdapter(a,android.R.layout.simple_spinner_dropdown_item,listOf("Я должен","Мне должны"))
            setSelection(if(payload.optString("direction")=="owed_to_me")1 else 0);box.addView(this)
        } else null
        val cash=if(kind.startsWith("debt"))CheckBox(a).apply {text="Деньги действительно переданы";isChecked=payload.optBoolean("cash_moved");box.addView(this)} else null
        val formatter=DateTimeFormatter.ofPattern("dd.MM.uuuu HH:mm").withResolverStyle(java.time.format.ResolverStyle.STRICT)
        val whenField=if(kind=="calendar")field("Дата и время: ДД.ММ.ГГГГ ЧЧ:ММ",try{OffsetDateTime.parse(payload.getString("starts_at")).atZoneSameInstant(ZoneId.systemDefault()).format(formatter)}catch(_:Exception){""}) else null
        val due=if(kind.startsWith("debt"))field("Срок долга: ГГГГ-ММ-ДД, можно пусто",if(payload.isNull("due_date"))"" else payload.getString("due_date")) else null
        val dialog=AlertDialog.Builder(a).setTitle("Уточнить поручение").setView(ScrollView(a).apply{addView(box)})
            .setNegativeButton("Закрыть",null).setPositiveButton("Применить",null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    require(description.text.isNotBlank());payload.put("description",description.text.toString())
                    if(amount!=null){val minor=BigDecimal(amount.text.toString().replace(',','.')).movePointRight(2).longValueExact();require(minor>0);payload.put("amount_minor",minor);payload.put("currency","KZT")}
                    if(person!=null){require(person.text.isNotBlank());payload.put("person",person.text.toString());payload.put("direction",if(direction!!.selectedItemPosition==1)"owed_to_me" else "i_owe");payload.put("cash_moved",cash!!.isChecked)}
                    if(due!=null)payload.put("due_date",if(due.text.isBlank())JSONObject.NULL else LocalDate.parse(due.text.toString()).toString())
                    if(whenField!=null){val date=LocalDateTime.parse(whenField.text.toString(),formatter).atZone(ZoneId.systemDefault()).toOffsetDateTime();require(date.isAfter(OffsetDateTime.now()));payload.put("starts_at",date.toString())}
                    payload.put("clarification",JSONObject.NULL)
                    val settings=SecureSettings(a)
                    Thread {
                        try {
                            val client=OkHttpClient.Builder().callTimeout(30,TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()
                            val req=Request.Builder().url(settings.server+"/actions/"+row.getString("id")).header("Authorization","Bearer ${settings.token()}").put(payload.toString().toRequestBody("application/json".toMediaType())).build()
                            client.newCall(req).execute().use {response->
                                if(!response.isSuccessful)throw IllegalStateException()
                            }
                            a.runOnUiThread{dialog.dismiss();ActionResults.show(a,recordingId)}
                        }catch(_:Exception){a.runOnUiThread{Toast.makeText(a,"Нет подтверждения. Обновите результат. Уже выполненное действие сначала отмените.",Toast.LENGTH_LONG).show()}}
                    }.start()
                }catch(_:Exception){Toast.makeText(a,"Проверьте сумму, имя и формат даты. Встреча должна быть в будущем.",Toast.LENGTH_LONG).show()}
            }
        }
        dialog.show()
    }
}
