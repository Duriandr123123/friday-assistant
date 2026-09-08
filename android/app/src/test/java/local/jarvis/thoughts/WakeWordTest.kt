package local.jarvis.thoughts

import org.junit.Assert.*
import org.junit.Test

class WakeWordTest {
    @Test fun waitsForStablePartialOrFinalWord() {
        val gate = WakeWordGate()
        assertFalse(gate.accept("сюзанна", false))
        assertTrue(gate.accept("сюзанна", false))
        assertTrue(WakeWordGate().accept("сузанна", true))
    }
    @Test fun revisedPartialDoesNotTrigger() {
        val gate = WakeWordGate()
        assertFalse(gate.accept("сюзанна", false))
        assertFalse(gate.accept("сезон", false))
        assertFalse(gate.accept("сюзанна", false))
    }
    @Test fun acceptsNameAndSpellingVariant() {
        assertTrue(WakeWord.matches("Сюзанна"))
        assertTrue(WakeWord.matches("сузанна запиши мысль"))
        assertTrue(WakeWord.matches("эй, СЮЗАННА!"))
    }
    @Test fun rejectsSimilarWordsAndEmptyAudio() {
        for (text in listOf("", "[unk]", "сюзан", "сюзанне", "рассказанно", "запиши мысль", "джарвис")) {
            assertFalse(text, WakeWord.matches(text))
        }
    }
}
