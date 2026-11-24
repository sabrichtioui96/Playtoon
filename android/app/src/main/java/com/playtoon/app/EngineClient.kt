package com.playtoon.app

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Single connection to the Playtoon engine: event stream over WebSocket + REST calls. */
object EngineClient {
    private const val TAG = "PlaytoonClient"
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state
    private var ws: WebSocket? = null
    private var wanted = false
    private var generation = 0
    lateinit var settings: Settings
        private set

    fun init(ctx: Context) {
        settings = Settings(ctx.applicationContext)
        _state.update { it.copy(serverUrl = settings.serverUrl) }
    }

    fun connect(url: String = settings.serverUrl) {
        settings.serverUrl = url.trimEnd('/')
        wanted = true
        generation++
        ws?.cancel()
        _state.update { it.copy(serverUrl = settings.serverUrl, connection = Connection.CONNECTING) }
        open(generation)
    }

    private fun open(gen: Int) {
        val wsUrl = settings.serverUrl.replaceFirst("http", "ws") + "/ws/client"
        val req = Request.Builder().url(wsUrl).build()
        ws = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (gen != generation) return
                _state.update { it.copy(connection = Connection.CONNECTED, lastError = null) }
                pushConfig()
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (gen == generation) handle(text)
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (gen != generation) return
                Log.w(TAG, "ws failure: $t")
                _state.update { it.copy(connection = Connection.DISCONNECTED, lastError = t.message) }
                retry(gen)
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (gen != generation) return
                _state.update { it.copy(connection = Connection.DISCONNECTED) }
                retry(gen)
            }
        })
    }

    private fun retry(gen: Int) {
        if (!wanted) return
        scope.launch {
            delay(2000)
            if (wanted && gen == generation) {
                _state.update { it.copy(connection = Connection.CONNECTING) }
                open(gen)
            }
        }
    }

    private fun handle(text: String) {
        val msg = try { JSONObject(text) } catch (e: Exception) { return }
        val data = msg.opt("data")
        when (val type = msg.optString("type")) {
            "hello" -> {
                val d = data as JSONObject
                val qs = linkedMapOf<String, Question>()
                d.optJSONArray("history").objects().reversed().forEach { o -> Question.from(o).let { qs[it.id] = it } }
                _state.update { it.copy(answerer = d.optString("answerer"), questions = qs,
                    remoteCapture = d.optJSONObject("capture")?.keys()?.asSequence()?.toList() ?: emptyList()) }
            }
            "reset" -> _state.update { it.copy(questions = linkedMapOf(), transcripts = emptyList()) }
            "audio.speech_start" -> _state.update { it.copy(speaking = true) }
            "transcript.final" -> {
                val d = data as JSONObject
                val t = Transcript(d.optString("text"), d.optString("language"), d.optDouble("confidence"),
                    d.optLong("asr_ms"), d.optDouble("duration_s"), d.optString("source"), msg.optString("ts"))
                _state.update { it.copy(speaking = false, transcripts = (listOf(t) + it.transcripts).take(100)) }
            }
            "capture.status" -> {
                val active = (data as JSONObject).optJSONObject("active")
                _state.update { it.copy(remoteCapture = active?.keys()?.asSequence()?.toList() ?: emptyList()) }
            }
            "config" -> {}
            else -> if (type.startsWith("question.") && data is JSONObject && data.has("question_id")) {
                val q = Question.from(data)
                _state.update { s ->
                    val m = LinkedHashMap(s.questions)
                    m[q.id] = q
                    s.copy(questions = m)
                }
            }
        }
    }

    fun setMic(active: Boolean) = _state.update { it.copy(micActive = active) }
    fun setScreen(active: Boolean) {
        _state.update { it.copy(screenActive = active) }
        ws?.send(JSONObject().put("type", "capture").put("key", "screen:android").put("active", active).toString())
    }
    fun setLevel(level: Float) = _state.update { it.copy(audioLevel = level) }

    fun pushConfig() = scope.launch {
        val body = JSONObject()
            .put("provider", settings.aiProvider)
            .put("model", settings.aiModel)
            .put("effort", settings.aiEffort)
            .put("language", settings.language)
            .put("translate_to", settings.translateTo)   // "" = keep original language
            .put("asr_vocabulary", settings.asrVocabulary)
        runCatching {
            http.newCall(Request.Builder().url(settings.serverUrl + "/config")
                .put(body.toString().toRequestBody("application/json".toMediaType())).build()).execute().close()
        }.onFailure { e -> _state.update { it.copy(lastError = "config: ${e.message}") } }
    }

    fun uploadImage(bytes: ByteArray, name: String, origin: String = "android-import") = scope.launch {
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, bytes.toRequestBody("image/*".toMediaType()))
            .addFormDataPart("origin", origin).build()
        runCatching {
            http.newCall(Request.Builder().url(settings.serverUrl + "/ingest/image").post(form).build()).execute().close()
        }.onFailure { e -> _state.update { it.copy(lastError = "upload: ${e.message}") } }
    }

    /** Screen frames: fire-and-forget; the server keeps only the newest frame per stream. */
    fun uploadFrame(jpeg: ByteArray) {
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "frame.jpg", jpeg.toRequestBody("image/jpeg".toMediaType()))
            .addFormDataPart("stream_id", "android-screen").build()
        runCatching {
            http.newCall(Request.Builder().url(settings.serverUrl + "/ingest/frame").post(form).build()).execute().close()
        }
    }

    fun clearHistory() = scope.launch {
        runCatching {
            http.newCall(Request.Builder().url(settings.serverUrl + "/reset")
                .post(ByteArray(0).toRequestBody()).build()).execute().close()
        }
    }
}
