package com.playtoon.app

import android.Manifest
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.QuestionAnswer
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.playtoon.app.capture.AudioCaptureService
import com.playtoon.app.capture.ScreenCaptureService
import com.playtoon.app.ui.AudioScreen
import com.playtoon.app.ui.HistoryScreen
import com.playtoon.app.ui.LiveScreen
import com.playtoon.app.ui.SettingsScreen
import com.playtoon.app.ui.StatusBar

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // Allows automation / adb to point the app at an engine: --es server_url http://host:8765
        intent?.getStringExtra("server_url")?.let { EngineClient.settings.serverUrl = it }
        EngineClient.connect()
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                PlaytoonRoot()
            }
        }
    }
}

@Composable
fun PlaytoonRoot() {
    val ctx = LocalContext.current
    val state by EngineClient.state.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }

    val notifPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val micPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) AudioCaptureService.start(ctx)
    }
    val projection = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        r.data?.let { ScreenCaptureService.start(ctx, r.resultCode, it) }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) {
            val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            if (bytes != null) EngineClient.uploadImage(bytes, uri.lastPathSegment ?: "screenshot.png")
        }
    }

    fun ensureNotifications() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val toggleMic: () -> Unit = {
        if (state.micActive) { AudioCaptureService.stop(ctx) } else {
            ensureNotifications()
            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
                AudioCaptureService.start(ctx)
            else micPerm.launch(Manifest.permission.RECORD_AUDIO)
        }
    }
    val toggleScreen: () -> Unit = {
        if (state.screenActive) { ScreenCaptureService.stop(ctx) } else {
            ensureNotifications()
            projection.launch(ctx.getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent())
        }
    }
    val importShot: () -> Unit = { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }

    Scaffold(
        topBar = { StatusBar(state) },
        bottomBar = {
            NavigationBar {
                listOf("Live" to Icons.Filled.QuestionAnswer, "Audio" to Icons.Filled.Mic,
                    "History" to Icons.Filled.History, "Settings" to Icons.Filled.Settings).forEachIndexed { i, (label, icon) ->
                    NavigationBarItem(selected = tab == i, onClick = { tab = i },
                        icon = { Icon(icon, contentDescription = label) }, label = { Text(label) })
                }
            }
        },
    ) { pad ->
        val m = Modifier.padding(pad)
        when (tab) {
            0 -> LiveScreen(state, importShot, m)
            1 -> AudioScreen(state, toggleMic, m)
            2 -> HistoryScreen(state, { EngineClient.clearHistory() }, m)
            else -> SettingsScreen(state, toggleScreen, m)
        }
    }
}
