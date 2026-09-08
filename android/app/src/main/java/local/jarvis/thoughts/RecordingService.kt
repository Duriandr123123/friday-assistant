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

class RecordingService : Service() {
    private val keepRecording = AtomicBoolean(false)
    private var thread: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private lateinit var audioManager: AudioManager
    private var originalMode = AudioManager.MODE_NORMAL
    companion object {
        @Volatile var active = false
        @Volatile var message = "Готов"
        const val STOP = "local.jarvis.STOP"
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
        return NotificationCompat.Builder(this, "recording").setSmallIcon(R.drawable.ic_mic)
            .setContentTitle("Джарвис слушает").setContentText("Нажмите «Остановить», когда закончите")
            .setOngoing(true).setContentIntent(open).addAction(R.drawable.ic_mic, "Остановить", stop).build()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { keepRecording.set(false); return START_NOT_STICKY }
        if (active) return START_NOT_STICKY
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            message = "Нет разрешения на микрофон"; stopSelf(); return START_NOT_STICKY
        }
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(1, notification())
        active = true; keepRecording.set(true); message = "Подключаю микрофон…"
        wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:recording").apply {
            acquire(11 * 60 * 1000L)
        }
        thread = Thread({ capture() }, "jarvis-audio").also { it.start() }
        return START_NOT_STICKY
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
        record.startRecording()
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
                val samples = ShortArray(1600)
                var total = 0
                var lastSync = SystemClock.elapsedRealtime()
                var lastSpeech = lastSync
                var heardSpeech = false
                var recovered = false
                val started = lastSync
                val silence = SecureSettings(this).silenceSeconds
                while (keepRecording.get() && total < Wav.RATE * 2 * 600) {
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
                    if (silence > 0 && heardSpeech && now - lastSpeech >= silence * 1000L && now - started > 5000) break
                }
                output.seek(0); output.write(Wav.header(total)); output.fd.sync()
            }
        } catch (_: Exception) {
            partialError = true
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
            store.close(); active = false; keepRecording.set(false)
            if (wakeLock?.isHeld == true) wakeLock?.release()
            stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
        }
    }
    override fun onDestroy() { keepRecording.set(false); super.onDestroy() }
}
