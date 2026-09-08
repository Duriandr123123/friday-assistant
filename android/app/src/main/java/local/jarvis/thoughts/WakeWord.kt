package local.jarvis.thoughts

object WakeWord {
    const val DISPLAY = "Сюзанна"
    // Both spellings represent the same spoken name; do not match substrings or 'Сюзан'.
    fun matches(text: String): Boolean = text.lowercase(java.util.Locale.ROOT)
        .split(Regex("[^а-яё]+" )).any { it == "сюзанна" || it == "сузанна" }
}

class WakeWordGate {
    private var consecutive = 0
    fun accept(text: String, final: Boolean): Boolean {
        consecutive = if (WakeWord.matches(text)) consecutive + 1 else 0
        return consecutive >= 2 || (final && consecutive > 0)
    }
}
