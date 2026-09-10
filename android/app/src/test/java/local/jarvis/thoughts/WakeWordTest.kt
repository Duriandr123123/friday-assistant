package local.jarvis.thoughts

import org.junit.Assert.*
import org.junit.Test

class WakeWordTest {
    @Test fun waitsForStablePartialOrFinalWord() {
        val gate = WakeWordGate()
        assertFalse(gate.accept("пятница", false))
        assertTrue(gate.accept("пятница", false))
        assertTrue(WakeWordGate().accept("пятница", true))
    }
    @Test fun revisedPartialDoesNotTrigger() {
        val gate = WakeWordGate()
        assertFalse(gate.accept("пятница", false))
        assertFalse(gate.accept("сезон", false))
        assertFalse(gate.accept("пятница", false))
    }
    @Test fun acceptsNameAndSpellingVariant() {
        assertTrue(WakeWord.matches("Пятница"))
        assertTrue(WakeWord.matches("пятница запиши мысль"))
        assertTrue(WakeWord.matches("эй, ПЯТНИЦА!"))
    }
    @Test fun rejectsSimilarWordsAndEmptyAudio() {
        for (text in listOf("", "[unk]", "сюзан", "сюзанне", "рассказанно", "запиши мысль", "джарвис")) {
            assertFalse(text, WakeWord.matches(text))
        }
    }
}
