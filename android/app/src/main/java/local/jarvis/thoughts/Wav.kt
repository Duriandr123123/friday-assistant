package local.jarvis.thoughts

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

object Wav {
    const val RATE = 16000
    fun header(dataSize: Int): ByteArray = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray()); putInt(dataSize + 36); put("WAVEfmt ".toByteArray())
        putInt(16); putShort(1); putShort(1); putInt(RATE); putInt(RATE * 2)
        putShort(2); putShort(16); put("data".toByteArray()); putInt(dataSize)
    }.array()
    fun repair(file: File) {
        RandomAccessFile(file, "rw").use { f ->
            require(f.length() >= 44) { "No audio header" }
            val bytes = ((f.length() - 44) / 2 * 2).toInt()
            f.setLength((44 + bytes).toLong()); f.seek(0); f.write(header(bytes)); f.fd.sync()
        }
    }
}
