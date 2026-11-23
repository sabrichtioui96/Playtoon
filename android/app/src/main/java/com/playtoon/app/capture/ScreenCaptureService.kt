package com.playtoon.app.capture

import android.app.Activity
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import com.playtoon.app.EngineClient
import com.playtoon.app.MainActivity
import com.playtoon.app.PlaytoonApp
import java.io.ByteArrayOutputStream

/**
 * Screen capture through MediaProjection (the OS consent dialog + system capture indicator apply).
 * Frames are sampled once per second; a frame is uploaded only when it differs from the last
 * uploaded one (cheap 16x16 luminance signature), so static screens cost nothing.
 */
class ScreenCaptureService : Service() {
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var worker: HandlerThread? = null
    private var lastSig: IntArray? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        val resultCode = intent?.getIntExtra(EXTRA_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data = intent?.let { IntentCompat.getParcelableExtra(it, EXTRA_DATA, Intent::class.java) }
        if (resultCode != Activity.RESULT_OK || data == null) { stopSelf(); return START_NOT_STICKY }

        val stop = PendingIntent.getService(this, 2, Intent(this, ScreenCaptureService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, PlaytoonApp.CAPTURE_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Playtoon is reading your screen")
            .setContentText("Screen frames are sent to your Playtoon engine for question detection")
            .setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
            .addAction(android.R.drawable.ic_media_pause, "Stop", stop)
            .build()
        // Must be in the foreground with type mediaProjection before obtaining the projection (Android 14+).
        startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)

        val mpm = getSystemService(MediaProjectionManager::class.java)
        val proj = mpm.getMediaProjection(resultCode, data) ?: run { stopSelf(); return START_NOT_STICKY }
        projection = proj
        val t = HandlerThread("playtoon-screen").also { it.start() }
        worker = t
        val handler = Handler(t.looper)
        proj.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopSelf() }
        }, handler)

        val metrics = resources.displayMetrics
        val scale = 720f / metrics.widthPixels.coerceAtLeast(1)
        val w = (metrics.widthPixels * scale).toInt()
        val h = (metrics.heightPixels * scale).toInt()
        val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader = r
        display = proj.createVirtualDisplay("playtoon", w, h, metrics.densityDpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            r.surface, null, handler)
        EngineClient.setScreen(true)
        handler.postDelayed(object : Runnable {
            override fun run() {
                grab(r)
                if (projection != null) handler.postDelayed(this, 1000)
            }
        }, 1000)
        return START_NOT_STICKY
    }

    private fun grab(r: ImageReader) {
        val img = r.acquireLatestImage() ?: return
        val bmp = try {
            val plane = img.planes[0]
            val rowPad = plane.rowStride - plane.pixelStride * img.width
            val b = Bitmap.createBitmap(img.width + rowPad / plane.pixelStride, img.height, Bitmap.Config.ARGB_8888)
            b.copyPixelsFromBuffer(plane.buffer)
            Bitmap.createBitmap(b, 0, 0, img.width, img.height)
        } finally {
            img.close()
        }
        val sig = signature(bmp)
        val prev = lastSig
        val changed = prev == null || sig.indices.count { kotlin.math.abs(sig[it] - prev[it]) > 12 } > 3
        if (!changed) return
        lastSig = sig
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 80, out)
        EngineClient.uploadFrame(out.toByteArray())
    }

    private fun signature(b: Bitmap): IntArray {
        val s = Bitmap.createScaledBitmap(b, 16, 16, true)
        return IntArray(256) { i ->
            val p = s.getPixel(i % 16, i / 16)
            ((p shr 16 and 0xff) * 3 + (p shr 8 and 0xff) * 6 + (p and 0xff)) / 10
        }
    }

    override fun onDestroy() {
        display?.release()
        reader?.close()
        projection?.stop()
        projection = null
        worker?.quitSafely()
        EngineClient.setScreen(false)
        super.onDestroy()
    }

    companion object {
        private const val NOTIF_ID = 12
        private const val EXTRA_CODE = "code"
        private const val EXTRA_DATA = "data"
        const val ACTION_STOP = "stop"
        fun start(ctx: Context, resultCode: Int, data: Intent) = ContextCompat.startForegroundService(ctx,
            Intent(ctx, ScreenCaptureService::class.java).putExtra(EXTRA_CODE, resultCode).putExtra(EXTRA_DATA, data))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, ScreenCaptureService::class.java))
    }
}
