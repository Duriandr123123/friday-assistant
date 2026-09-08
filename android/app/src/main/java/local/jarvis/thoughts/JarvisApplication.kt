package local.jarvis.thoughts

import android.app.Application

class JarvisApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        LocalStore(this).use { it.recover() }
        UploadWorker.enqueue(this)
    }
}
