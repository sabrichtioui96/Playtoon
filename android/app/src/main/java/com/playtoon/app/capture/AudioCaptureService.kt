package com.playtoon.app.capture

import android.Manifest
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.playtoon.app.EngineClient
import com.playtoon.app.MainActivity
import com.playtoon.app.PlaytoonApp
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import kotlin.math.sqrt

/**
 * Streams the microphone (16 kHz mono PCM16) to the engine's /ws/audio endpoint.
 * Runs only as a foreground service with an ongoing notification; Android additionally shows its
 * own privacy indicator while the microphone is in use. Nothing is recorded to disk.
 */
class AudioCaptureService : Service() {
    @Volatile private var running = false
    private var thread: Thread? = null
    private var socket: WebSocket? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIF_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        if (!running) start()
        return START_NOT_STICKY
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, AudioCaptureService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, PlaytoonApp.CAPTURE_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Playtoon is listening")
            .setContentText("Microphone audio is streamed to your Playtoon engine")
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stop)
            .build()
    }

    private fun start() {
        running = true
        val s = EngineClient.settings
        val url = s.serverUrl.replaceFirst("http", "ws") + "/ws/audio?language=${s.language}&device=android"
        socket = EngineClient.http.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "audio socket failed: $t")
                stopSelf()
            }
        })
        EngineClient.setMic(true)
        thread = Thread({ loop() }, "playtoon-mic").also { it.start() }
    }

    @Suppress("MissingPermission")
    private fun loop() {
        val rate = 16000
        val minBuf = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val chunk = rate / 10 * 2                       // 100 ms of PCM16
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, rate, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, chunk * 4))
        // Platform DSP where available; the server applies its own noise gate as well.
        val ns = if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId)?.apply { enabled = true } else null
        val agc = if (AutomaticGainControl.isAvailable()) AutomaticGainControl.create(rec.audioSessionId)?.apply { enabled = true } else null
        val buf = ByteArray(chunk)
        try {
            rec.startRecording()
            while (running) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                socket?.send(buf.toByteString(0, n))
                var sum = 0.0
                var i = 0
                while (i + 1 < n) {
                    val v = ((buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xff)).toShort() / 32768.0
                    sum += v * v
                    i += 2
                }
                EngineClient.setLevel(sqrt(sum / (n / 2)).toFloat())
            }
        } catch (e: Exception) {
            Log.e(TAG, "capture failed", e)
        } finally {
            runCatching { rec.stop() }
            rec.release()
            ns?.release()
            agc?.release()
        }
    }

    override fun onDestroy() {
        running = false
        thread?.join(500)
        socket?.send("{\"type\":\"stop\"}")
        socket?.close(1000, "stopped")
        EngineClient.setMic(false)
        EngineClient.setLevel(0f)
        super.onDestroy()
    }

    companion object {
        private const val TAG = "PlaytoonMic"
        private const val NOTIF_ID = 11
        const val ACTION_STOP = "stop"
        fun start(ctx: Context) = ContextCompat.startForegroundService(ctx, Intent(ctx, AudioCaptureService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, AudioCaptureService::class.java))
    }
}
