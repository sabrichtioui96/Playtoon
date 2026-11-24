package com.playtoon.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.playtoon.app.Connection
import com.playtoon.app.EngineClient
import com.playtoon.app.Question
import com.playtoon.app.UiState

private val LANG_NAMES = mapOf("en" to "English", "fr" to "Français", "ar" to "العربية")

@Composable
fun StatusBar(s: UiState) {
    Surface(tonalElevation = 3.dp) {
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("Playtoon", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(12.dp))
            val (color, label) = when (s.connection) {
                Connection.CONNECTED -> Color(0xFF2E7D32) to "Connected"
                Connection.CONNECTING -> Color(0xFFF9A825) to "Connecting…"
                Connection.DISCONNECTED -> Color(0xFFC62828) to "Offline"
            }
            Box(Modifier.size(10.dp).clip(CircleShape).background(color))
            Spacer(Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.weight(1f))
            // Privacy indicators: always visible while any capture is active
            if (s.micActive) RecBadge("MIC")
            if (s.screenActive) RecBadge("SCREEN")
        }
    }
}

@Composable
private fun RecBadge(what: String) {
    Row(Modifier.padding(start = 6.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFFD32F2F))
        .padding(horizontal = 8.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(Color.White))
        Spacer(Modifier.width(4.dp))
        Text("$what ON", color = Color.White, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun LiveScreen(s: UiState, importShot: () -> Unit, modifier: Modifier) {
    val qs = s.questions.values.reversed().take(30)
    Box(modifier.fillMaxSize()) {
        if (qs.isEmpty()) {
            Column(Modifier.align(Alignment.Center).padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Waiting for questions…", style = MaterialTheme.typography.titleMedium)
                Text("Enable the microphone, screen capture, the browser extension, or import a screenshot.",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp, 12.dp, 12.dp, 96.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(qs, key = { it.id }) { QuestionCard(it) }
        }
        ExtendedFloatingActionButton(onClick = importShot, modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
            icon = { Icon(Icons.Filled.AddPhotoAlternate, null) }, text = { Text("Import screenshot") })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun QuestionCard(q: Question) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors()) {
        Column(Modifier.padding(14.dp)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Tag("Source: ${q.sourceLabel}")
                Tag("Language: ${LANG_NAMES[q.language] ?: q.language}")
                Tag(q.status.replace('_', ' '))
                if (q.revision > 0) Tag("rev ${q.revision}")
            }
            Spacer(Modifier.height(8.dp))
            Text(q.text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (q.options.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                q.options.forEachIndexed { i, o ->
                    val chosen = q.answer?.optionIndex == i
                    Text("${'A' + i}) $o" + if (chosen) "  ✓" else "",
                        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp).clip(RoundedCornerShape(6.dp))
                            .background(if (chosen) Color(0x332E7D32) else Color.Transparent).padding(6.dp),
                        fontWeight = if (chosen) FontWeight.Bold else FontWeight.Normal)
                }
            }
            q.discrepancies.forEach { d ->
                Text("⚠ ${d.field} differ: " + d.values.entries.joinToString(" / ") { "${it.key}: ${it.value}" } + " — ${d.resolution}",
                    style = MaterialTheme.typography.bodySmall, color = Color(0xFFE65100))
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            val a = q.answer
            if (a == null && q.status == "failed") {
                Text("Could not get an answer", style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.error)
                Text(q.error ?: "The AI request failed. Check the engine log on the PC.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            } else if (a == null) {
                Text(when (q.status) {
                    "analyzing" -> "Analyzing…"
                    "incomplete" -> "Waiting for a complete question…"
                    else -> "Preparing answer…"
                }, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (q.status == "analyzing") LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 4.dp))
            } else {
                Text("Suggested answer: ${a.suggested ?: "—"}", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text("Confidence: ${(a.confidence * 100).toInt()}%  ·  Detection: ${(q.confidence * 100).toInt()}%",
                    style = MaterialTheme.typography.bodySmall)
                if (a.explanation.isNotBlank()) Text(a.explanation, style = MaterialTheme.typography.bodyMedium)
                Text("Processing: ${q.processingMs ?: a.durationMs} ms (model ${a.durationMs} ms) · ${a.provider}${a.model?.let { " / $it" } ?: ""}",
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun Tag(t: String) {
    Text(t, style = MaterialTheme.typography.labelSmall, modifier = Modifier.clip(RoundedCornerShape(8.dp))
        .background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 8.dp, vertical = 3.dp),
        color = MaterialTheme.colorScheme.onSecondaryContainer)
}

@Composable
fun AudioScreen(s: UiState, toggleMic: () -> Unit, modifier: Modifier) {
    Column(modifier.fillMaxSize().padding(16.dp)) {
        Button(onClick = toggleMic, modifier = Modifier.fillMaxWidth()) {
            Icon(if (s.micActive) Icons.Filled.MicOff else Icons.Filled.Mic, null)
            Spacer(Modifier.width(8.dp))
            Text(if (s.micActive) "Stop listening" else "Start listening (microphone)")
        }
        Spacer(Modifier.height(8.dp))
        LinearProgressIndicator(progress = { (s.audioLevel * 8).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
        Text(when {
            !s.micActive -> "Microphone off"
            s.speaking -> "Speech detected — transcribing…"
            else -> "Listening for speech"
        }, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(vertical = 6.dp))
        if (s.remoteCapture.any { it.startsWith("microphone") && !s.micActive })
            Text("Another device is streaming audio to this engine.", style = MaterialTheme.typography.bodySmall)
        HorizontalDivider()
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 8.dp)) {
            items(s.transcripts) { t ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(t.text, style = MaterialTheme.typography.bodyLarge)
                        Text("${LANG_NAMES[t.language] ?: t.language} · ${(t.confidence * 100).toInt()}% · ${t.durationS}s audio · ASR ${t.asrMs} ms · ${t.source}",
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
fun HistoryScreen(s: UiState, clear: () -> Unit, modifier: Modifier) {
    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("${s.questions.size} questions", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.weight(1f))
            OutlinedButton(onClick = clear) { Text("Clear") }
        }
        LazyColumn {
            items(s.questions.values.reversed().toList(), key = { it.id }) { q ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Text(q.text, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge)
                    Text("${q.timestamp.take(19).replace('T', ' ')} · ${q.sourceLabel} · ${q.language} · " +
                            (q.answer?.suggested?.let { "→ $it" } ?: q.status),
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
fun SettingsScreen(s: UiState, toggleScreen: () -> Unit, modifier: Modifier) {
    val st = EngineClient.settings
    var url by remember { mutableStateOf(st.serverUrl) }
    var provider by remember { mutableStateOf(st.aiProvider) }
    var model by remember { mutableStateOf(st.aiModel) }
    var effort by remember { mutableStateOf(st.aiEffort) }
    var lang by remember { mutableStateOf(st.language) }
    var translate by remember { mutableStateOf(st.translateTo.isNotBlank()) }
    var vocab by remember { mutableStateOf(st.asrVocabulary) }
    LazyColumn(modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text("Connection", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(url, { url = it }, label = { Text("Engine URL") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(onClick = { EngineClient.connect(url) }) { Text("Connect") }
            Text("Status: ${s.connection.name.lowercase()} · answerer: ${s.answerer}" + (s.lastError?.let { " · $it" } ?: ""),
                style = MaterialTheme.typography.bodySmall)
        }
        item {
            Text("AI configuration", style = MaterialTheme.typography.titleMedium)
            ChipRow(listOf("auto", "groq", "xai", "anthropic", "offline"), provider) { provider = it }
            Text("The API key is set on the PC running the engine (GROQ_API_KEY / XAI_API_KEY / ANTHROPIC_API_KEY).",
                style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(model, { model = it }, label = { Text("Model (empty = provider default)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth())
            Text("Effort", style = MaterialTheme.typography.labelMedium)
            ChipRow(listOf("low", "medium", "high"), effort) { effort = it }
        }
        item {
            Text("Language", style = MaterialTheme.typography.titleMedium)
            Text("Spoken language (auto-detects English, French and Arabic)", style = MaterialTheme.typography.bodySmall)
            ChipRow(listOf("auto", "en", "fr", "ar"), lang) { lang = it }
            OutlinedTextField(vocab, { vocab = it }, label = { Text("Topic vocabulary (optional)") },
                supportingText = { Text("Names and terms for this game, e.g. \"Python, len(), Abuja\". Improves spelling in speech.") },
                modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(translate, { translate = it })
                Spacer(Modifier.width(8.dp))
                Text("Translate questions to English before analysis (off = keep original language)")
            }
            Button(onClick = {
                st.aiProvider = provider; st.aiModel = model; st.aiEffort = effort; st.language = lang
                st.translateTo = if (translate) "en" else ""
                st.asrVocabulary = vocab.trim()
                EngineClient.pushConfig()
            }) { Text("Apply") }
        }
        item {
            Text("Screen capture", style = MaterialTheme.typography.titleMedium)
            Text("Uses Android's screen-capture permission. Android asks for consent each time and shows its own capture indicator.",
                style = MaterialTheme.typography.bodySmall)
            Button(onClick = toggleScreen) { Text(if (s.screenActive) "Stop screen capture" else "Start screen capture") }
        }
    }
}

@Composable
private fun ChipRow(options: List<String>, selected: String, onSelect: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { o -> FilterChip(selected = o == selected, onClick = { onSelect(o) }, label = { Text(o) }) }
    }
}
