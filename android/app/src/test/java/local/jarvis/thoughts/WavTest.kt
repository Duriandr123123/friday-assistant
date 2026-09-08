package local.jarvis.thoughts

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class WavTest {
    @Test fun repairsInterruptedFileWithoutLosingSamples() {
        val f = File.createTempFile("jarvis", ".wav")
        try {
            val samples = byteArrayOf(1, 2, 3, 4, 5, 6)
            f.writeBytes(Wav.header(0) + samples)
            Wav.repair(f)
            val bytes = f.readBytes()
            assertEquals(6, ByteBuffer.wrap(bytes, 40, 4).order(ByteOrder.LITTLE_ENDIAN).int)
            assertArrayEquals(samples, bytes.copyOfRange(44, bytes.size))
        } finally { f.delete() }
    }
    @Test fun rejectsPublicCleartextAndCredentialUrls() {
        assertFalse(SecureSettings.validServer("http://example.com"))
        assertFalse(SecureSettings.validServer("https://token@example.com"))
        assertTrue(SecureSettings.validServer("http://192.168.1.10:8765"))
        assertTrue(SecureSettings.validServer("https://notes.example.com"))
    }
}
