package local.jarvis.thoughts

import android.content.Context
import org.vosk.Model
import java.io.File
import java.io.InterruptedIOException
import java.util.zip.ZipInputStream

object WakeModel {
    fun load(context: Context, cancelled: () -> Boolean): Model {
        val folder = File(context.filesDir, "wake-model-ru-0.22")
        val marker = File(folder, ".ready")
        if (!marker.exists()) {
            folder.mkdirs()
            ZipInputStream(context.assets.open("wake-model.zip")).use { zip ->
                var entry = zip.nextEntry
                val buffer = ByteArray(65536)
                while (entry != null) {
                    if (cancelled()) throw InterruptedIOException()
                    val relative = entry.name.substringAfter('/', "")
                    if (relative.isNotEmpty()) {
                        val target = File(folder, relative)
                        require(target.canonicalPath.startsWith(folder.canonicalPath + File.separator))
                        if (entry.isDirectory) target.mkdirs() else {
                            target.parentFile?.mkdirs()
                            target.outputStream().use { out ->
                                var count = zip.read(buffer)
                                while (count >= 0) {
                                    if (cancelled()) throw InterruptedIOException()
                                    out.write(buffer, 0, count); count = zip.read(buffer)
                                }
                                out.fd.sync()
                            }
                        }
                    }
                    zip.closeEntry(); entry = zip.nextEntry
                }
            }
            marker.writeText("ready")
        }
        if (cancelled()) throw InterruptedIOException()
        return Model(folder.absolutePath)
    }
}
