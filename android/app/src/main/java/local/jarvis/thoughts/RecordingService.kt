package local.jarvis.thoughts

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.*
import android.os.*
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt
import org.vosk.Model
import org.vosk.Recognizer
import org.json.JSONObject

class RecordingService : Service() {
    private val keepRecording = AtomicBoolean(false)
    private var thread: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private lateinit var audioManager: AudioManager
    private var originalMode = AudioManager.MODE_NORMAL
    private val manualRecording = AtomicBoolean(false)
    private var model: Model? = null
    private var voiceTriggered = false
    companion object {
        @Volatile var active = false
        @Volatile var running = false
        @Volatile var backgroundEnabled = false
        @Volatile var backgroundError: String? = null
        @Volatile var message = "Готов"
        const val STOP = "local.jarvis.STOP"
        const val ENABLE_BACKGROUND = "local.jarvis.ENABLE_BACKGROUND"
        const val DISABLE_BACKGROUND = "local.jarvis.DISABLE_BACKGROUND"
    }
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        audioManager = getSystemService(AudioManager::class.java)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("recording", "Запись мысли", NotificationManager.IMPORTANCE_LOW))
    }
    private fun notification(): Notification {
        val stop = PendingIntent.getService(this, 0, Intent(this, RecordingService::class.java).setAction(STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val disable = PendingIntent.getService(this, 3, Intent(this, RecordingService::class.java).setAction(DISABLE_BACKGROUND),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val builder = NotificationCompat.Builder(this, "recording").setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(if (active) "Записываю мысль" else "Ожидаю: Пятница")
            .setContentText(if (active) "Нажмите «Остановить запись», когда закончите" else "Фоновый микрофон включён · распознавание на телефоне")
            .setOngoing(true).setContentIntent(open)
        if (active) builder.addAction(R.drawable.ic_mic, "Остановить запись", stop)
        if (backgroundEnabled) builder.addAction(R.drawable.ic_mic, "Выключить фон", disable)
        return builder.build()
    }
    private fun updateNotification() { getSystemService(NotificationManager::class.java).notify(1, notification()) }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { keepRecording.set(false); return START_NOT_STICKY }
        if (intent?.action == DISABLE_BACKGROUND) {
            backgroundEnabled = false; manualRecording.set(false); keepRecording.set(false)
            message = "Фоновое прослушивание выключено"
            if (!running) stopSelf()
            return START_NOT_STICKY
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            message = "Нет разрешения на микрофон"; stopSelf(); return START_NOT_STICKY
        }
        if (intent?.action == ENABLE_BACKGROUND) { backgroundEnabled = true; backgroundError = null }
        else if (!active) manualRecording.set(true)
        if (running) { updateNotification(); return START_NOT_STICKY }
        running = true
        if (Build.VERSION.SDK_INT >= 30) startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(1, notification())
        message = "Подключаю микрофон…"
        wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:recording").apply {
            acquire(60 * 60 * 1000L)
        }
        thread = Thread({ session() }, "jarvis-audio").also { it.start() }
        return START_NOT_STICKY
    }
    private fun session() {
        try {
            while (backgroundEnabled || manualRecording.get()) {
                voiceTriggered = !manualRecording.get()
                if (voiceTriggered && !waitForWakeWord()) continue
                if (!backgroundEnabled && !manualRecording.get()) break
                manualRecording.set(false)
                active = true; keepRecording.set(true); updateNotification()
                capture()
                active = false
                if (backgroundEnabled) updateNotification()
            }
        } catch (_: Exception) {
            message = if (backgroundEnabled) "Фон остановлен: не удалось открыть модель или микрофон. Включите режим снова." else "Фоновое прослушивание выключено"
            if (backgroundEnabled) backgroundError = message
        } finally {
            model?.close(); model = null
            backgroundEnabled = false; active = false; running = false; keepRecording.set(false)
            if (wakeLock?.isHeld == true) wakeLock?.release()
            stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
        }
    }
    private fun renewWakeLock() {
        if (wakeLock?.isHeld == false) wakeLock?.acquire(60 * 60 * 1000L)
    }
    private fun waitForWakeWord(): Boolean {
        if (model == null) {
            message = "Готовлю распознавание слова «Пятница»…"
            model = WakeModel.load(this) { !backgroundEnabled }
        }
        if (!backgroundEnabled || manualRecording.get()) return false
        // Full vocabulary avoids forcing every unrelated sound into the one-word grammar.
        Recognizer(model, Wav.RATE.toFloat()).use { recognizer ->
            var mic: AudioRecord? = null
            try {
                originalMode = audioManager.mode
                mic = recorder(false) // Idle listening uses phone mic; it does not hold Bluetooth SCO open.
                message = "Работаю в фоне · скажите «Пятница»"
                updateNotification()
                vibrateRecord()
                val samples = ShortArray(1600)
                val gate = WakeWordGate()
                var resetAt = SystemClock.elapsedRealtime()
                while (backgroundEnabled && !manualRecording.get()) {
                    renewWakeLock()
                    val count = mic.read(samples, 0, samples.size, AudioRecord.READ_BLOCKING)
                    if (count <= 0) error("wake_microphone_read")
                    val final = recognizer.acceptWaveForm(samples, count)
                    val result = JSONObject(if (final) recognizer.result else recognizer.partialResult)
                    if (gate.accept(result.optString(if (final) "text" else "partial"), final)) return true
                    if (SystemClock.elapsedRealtime() - resetAt > 30000) {
                        recognizer.reset(); resetAt = SystemClock.elapsedRealtime()
                    }
                }
                return false
            } finally {
                try { mic?.stop() } catch (_: Exception) { }
                mic?.release()
            }
        }
    }
    @Suppress("MissingPermission", "DEPRECATION")
    private fun selectBluetooth(): Boolean {
        originalMode = audioManager.mode
        if (!SecureSettings(this).bluetooth) return false
        if (Build.VERSION.SDK_INT >= 31 && ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return false
        return try {
            if (Build.VERSION.SDK_INT >= 31) {
                val device = audioManager.availableCommunicationDevices.firstOrNull {
                    it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
                }
                if (device != null) {
                    audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
                    val selected = audioManager.setCommunicationDevice(device)
                    if (selected) Thread.sleep(500)
                    selected
                } else false
            } else {
                val present = audioManager.getDevices(AudioManager.GET_DEVICES_INPUTS).any { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
                if (present && audioManager.isBluetoothScoAvailableOffCall) {
                    audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
                    audioManager.startBluetoothSco()
                    Thread.sleep(1200)
                    audioManager.isBluetoothScoOn = true
                    true
                } else false
            }
        } catch (_: Exception) { false }
    }
    @Suppress("DEPRECATION")
    private fun clearRoute() {
        try {
            if (Build.VERSION.SDK_INT >= 31) audioManager.clearCommunicationDevice()
            else { audioManager.stopBluetoothSco(); audioManager.isBluetoothScoOn = false }
            audioManager.mode = originalMode
        } catch (_: Exception) { }
    }
    @Suppress("MissingPermission")
    private fun recorder(bluetooth: Boolean): AudioRecord {
        val min = AudioRecord.getMinBufferSize(Wav.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord.Builder()
            .setAudioSource(if (bluetooth) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.MIC)
            .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(Wav.RATE)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
            .setBufferSizeInBytes(maxOf(min, 6400)).build()
        if (record.state != AudioRecord.STATE_INITIALIZED) { record.release(); error("microphone_init") }
        if (!bluetooth) audioManager.getDevices(AudioManager.GET_DEVICES_INPUTS)
            .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }?.let { record.preferredDevice = it }
        try { record.startRecording() } catch (e: Exception) { record.release(); throw e }
        return record
    }
    private fun capture() {
        val store = LocalStore(this)
        var row: LocalRecording? = null
        var audio: AudioRecord? = null
        var partialError = false
        try {
            row = store.create(File(filesDir, "audio"))
            RandomAccessFile(row.path, "rw").use { output ->
                output.write(Wav.header(0)); output.fd.sync()
                var bluetooth = selectBluetooth()
                audio = try { recorder(bluetooth) } catch (e: Exception) {
                    if (!bluetooth) throw e
                    bluetooth = false; clearRoute(); recorder(false)
                }
                message = "Слушаю · " + if (bluetooth) "гарнитура" else "микрофон телефона"
                if (voiceTriggered) {
                    val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 70)
                    tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
                    Handler(Looper.getMainLooper()).postDelayed({ tone.release() }, 200)
                }
                vibrateRecord()
                val samples = ShortArray(1600)
                var total = 0
                var lastSync = SystemClock.elapsedRealtime()
                var lastSpeech = lastSync
                var heardSpeech = false
                var recovered = false
                val started = lastSync
                val silence = SecureSettings(this).silenceSeconds
                while (keepRecording.get() && total < Wav.RATE * 2 * 600) {
                    renewWakeLock()
                    val count = audio!!.read(samples, 0, samples.size, AudioRecord.READ_BLOCKING)
                    if (count <= 0) {
                        if (!recovered) {
                            try { audio?.stop() } catch (_: Exception) { }
                            audio?.release(); clearRoute(); audio = recorder(false); recovered = true
                            message = "Слушаю · переключено на телефон"; continue
                        }
                        error("microphone_read")
                    }
                    val bytes = ByteBuffer.allocate(count * 2).order(ByteOrder.LITTLE_ENDIAN)
                    var square = 0.0
                    for (i in 0 until count) { bytes.putShort(samples[i]); square += samples[i].toDouble() * samples[i] }
                    output.write(bytes.array()); total += count * 2
                    val now = SystemClock.elapsedRealtime()
                    if (sqrt(square / count) > 500) { lastSpeech = now; heardSpeech = true }
                    if (now - lastSync >= 1000) { output.fd.sync(); lastSync = now }
                    if (silence > 0 && heardSpeech && now - lastSpeech >= silence * 1000L) break
                    if (voiceTriggered && !heardSpeech && now - started >= 15000) break
                }
                output.seek(0); output.write(Wav.header(total)); output.fd.sync()
            }
        } catch (_: Exception) {
            partialError = true
            if (row == null) message = "Не удалось создать файл. Проверьте свободное место."
        } finally {
            try { audio?.stop() } catch (_: Exception) { }
            audio?.release(); clearRoute()
            row?.let {
                val file = File(it.path)
                try {
                    if (file.length() >= 3244) {
                        Wav.repair(file)
                        store.update(it.id, "queued", if (partialError) "Запись прервалась; доступный звук сохранён" else "")
                        message = if (partialError) "Запись прервана. Звук сохранён" else "Записано на телефоне · отправляю"
                        UploadWorker.enqueue(this)
                    } else {
                        store.update(it.id, "local_error", "Запись слишком короткая или микрофон недоступен")
                        message = "Не удалось записать звук"
                    }
                } catch (_: Exception) { message = "Ошибка сохранения; проверьте свободное место" }
            }
            vibrateRecord()
            store.close(); keepRecording.set(false)
        }
    }
    private fun vibrateRecord() {
        try { (getSystemService(VIBRATOR_SERVICE) as android.os.Vibrator).vibrate(android.os.VibrationEffect.createOneShot(90, android.os.VibrationEffect.DEFAULT_AMPLITUDE)) } catch (_: Exception) { }
    }
    override fun onDestroy() { backgroundEnabled = false; manualRecording.set(false); keepRecording.set(false); super.onDestroy() }
}
