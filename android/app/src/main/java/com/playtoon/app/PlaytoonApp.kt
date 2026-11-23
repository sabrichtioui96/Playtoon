package com.playtoon.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class PlaytoonApp : Application() {
    override fun onCreate() {
        super.onCreate()
        EngineClient.init(this)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CAPTURE_CHANNEL, "Active capture", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shown whenever Playtoon is recording the microphone or capturing the screen"
            })
    }

    companion object {
        const val CAPTURE_CHANNEL = "capture"
    }
}
