package local.jarvis.thoughts

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.net.URI

class SecureSettings(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    var server: String
        get() = prefs.getString("server", "") ?: ""
        set(value) { prefs.edit().putString("server", value.trim().trimEnd('/')).commit() }
    var silenceSeconds: Int
        get() = prefs.getInt("silence_v2", 2).coerceIn(1, 10)
        set(value) { prefs.edit().putInt("silence_v2", value.coerceIn(1, 10)).commit() }
    var autoSend: Boolean
        get() = prefs.getBoolean("auto_send", true)
        set(value) { prefs.edit().putBoolean("auto_send", value).commit() }
    var bluetooth: Boolean
        get() = prefs.getBoolean("bluetooth", true)
        set(value) { prefs.edit().putBoolean("bluetooth", value).commit() }
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("jarvis-token", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("jarvis-token", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun token(): String {
        val encoded = prefs.getString("token", null) ?: return ""
        return try {
            val bytes = Base64.decode(encoded, Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        } catch (_: Exception) { "" }
    }
    fun saveToken(value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        prefs.edit().putString("token", Base64.encodeToString(cipher.iv + cipher.doFinal(value.trim().toByteArray()), Base64.NO_WRAP)).commit()
    }
    companion object {
        fun validServer(value: String): Boolean = try {
            val uri = URI(value)
            val host = uri.host ?: ""
            val parts = host.split('.').mapNotNull { it.toIntOrNull() }
            val privateIp = parts.size == 4 && parts.all { it in 0..255 } &&
                (parts[0] == 10 || (parts[0] == 192 && parts[1] == 168) ||
                 (parts[0] == 172 && parts[1] in 16..31) || (parts[0] == 100 && parts[1] in 64..127) || parts[0] == 127)
            uri.userInfo == null && uri.query == null && uri.fragment == null &&
                (uri.path.isNullOrEmpty() || uri.path == "/") && host.isNotEmpty() &&
                (uri.scheme == "https" || uri.scheme == "http" && privateIp)
        } catch (_: Exception) { false }
    }
}
