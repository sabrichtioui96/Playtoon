package com.playtoon.app

import org.json.JSONArray
import org.json.JSONObject

data class Answer(
    val suggested: String?,
    val optionIndex: Int?,
    val confidence: Double,
    val explanation: String,
    val provider: String,
    val model: String?,
    val durationMs: Long,
)

data class Discrepancy(val field: String, val values: Map<String, String>, val resolution: String)

data class Question(
    val id: String,
    val text: String,
    val source: List<String>,          // "visual", "audio"
    val channels: List<String>,        // browser, chat, visual, audio
    val language: String,
    val options: List<String>,
    val timestamp: String,
    val confidence: Double,
    val status: String,
    val revision: Int,
    val context: List<String>,
    val discrepancies: List<Discrepancy>,
    val answer: Answer?,
    val processingMs: Long?,
) {
    val sourceLabel: String
        get() = when {
            source.size > 1 -> "visual + audio"
            source.isEmpty() -> "-"
            else -> source.first()
        }

    companion object {
        fun from(o: JSONObject): Question {
            val a = o.optJSONObject("answer")
            return Question(
                id = o.getString("question_id"),
                text = o.optString("question_text"),
                source = o.optJSONArray("source").strings(),
                channels = o.optJSONArray("channels").strings(),
                language = o.optString("language", "und"),
                options = o.optJSONArray("options").strings(),
                timestamp = o.optString("timestamp"),
                confidence = o.optDouble("confidence", 0.0),
                status = o.optString("status"),
                revision = o.optInt("revision", 0),
                context = o.optJSONArray("context").strings(),
                discrepancies = o.optJSONArray("discrepancies").objects().map { d ->
                    val vals = d.optJSONObject("values") ?: JSONObject()
                    Discrepancy(d.optString("field"), vals.keys().asSequence().associateWith { vals.optString(it) },
                        d.optString("resolution"))
                },
                answer = a?.let {
                    Answer(
                        suggested = if (it.isNull("suggested_answer")) null else it.optString("suggested_answer"),
                        optionIndex = if (it.isNull("option_index")) null else it.optInt("option_index"),
                        confidence = it.optDouble("confidence", 0.0),
                        explanation = it.optString("explanation"),
                        provider = it.optString("provider"),
                        model = if (it.isNull("model")) null else it.optString("model"),
                        durationMs = it.optLong("duration_ms"),
                    )
                },
                processingMs = if (o.isNull("processing_ms")) null else o.optLong("processing_ms"),
            )
        }
    }
}

data class Transcript(
    val text: String,
    val language: String,
    val confidence: Double,
    val asrMs: Long,
    val durationS: Double,
    val source: String,
    val timestamp: String,
)

enum class Connection { DISCONNECTED, CONNECTING, CONNECTED }

data class UiState(
    val connection: Connection = Connection.DISCONNECTED,
    val serverUrl: String = "",
    val answerer: String = "?",
    val questions: Map<String, Question> = linkedMapOf(),
    val transcripts: List<Transcript> = emptyList(),
    val speaking: Boolean = false,
    val micActive: Boolean = false,
    val screenActive: Boolean = false,
    val remoteCapture: List<String> = emptyList(),
    val audioLevel: Float = 0f,
    val lastError: String? = null,
)

fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).map { optString(it) }

fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }
