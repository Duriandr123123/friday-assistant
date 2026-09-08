package local.jarvis.thoughts

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.io.File
import java.time.OffsetDateTime
import java.util.UUID

data class LocalRecording(val id: String, val path: String, val capturedAt: String,
    val status: String, val error: String, val serverJson: String)

class LocalStore(context: Context) : SQLiteOpenHelper(context, "recordings.db", null, 1) {
    init { setWriteAheadLoggingEnabled(true) }
    override fun onConfigure(db: SQLiteDatabase) { db.execSQL("PRAGMA synchronous=FULL") }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE recordings(id TEXT PRIMARY KEY,path TEXT NOT NULL,captured_at TEXT NOT NULL,status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',server_json TEXT NOT NULL DEFAULT '')")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    fun create(folder: File): LocalRecording {
        folder.mkdirs()
        val id = UUID.randomUUID().toString()
        val row = LocalRecording(id, File(folder, "$id.wav").absolutePath, OffsetDateTime.now().toString(), "recording", "", "")
        writableDatabase.insertOrThrow("recordings", null, ContentValues().apply {
            put("id", row.id); put("path", row.path); put("captured_at", row.capturedAt); put("status", row.status)
        })
        return row
    }
    fun update(id: String, status: String, error: String = "", serverJson: String? = null) {
        writableDatabase.update("recordings", ContentValues().apply {
            put("status", status); put("error", error); if (serverJson != null) put("server_json", serverJson)
        }, "id=?", arrayOf(id))
    }
    fun all(): List<LocalRecording> = readableDatabase.rawQuery("SELECT * FROM recordings ORDER BY captured_at DESC", null).use { c ->
        buildList { while (c.moveToNext()) add(LocalRecording(c.getString(0), c.getString(1), c.getString(2), c.getString(3), c.getString(4), c.getString(5))) }
    }
    fun recover() {
        all().filter { it.status == "recording" }.forEach { row ->
            val file = File(row.path)
            if (file.exists() && file.length() > 44 + 3200) {
                try { Wav.repair(file); update(row.id, "queued", "Восстановлена после прерывания") }
                catch (_: Exception) { update(row.id, "local_error", "Не удалось восстановить аудио; файл сохранён") }
            } else update(row.id, "local_error", "Запись прервана до появления звука")
        }
    }
}
