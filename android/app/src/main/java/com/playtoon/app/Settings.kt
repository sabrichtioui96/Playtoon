package com.playtoon.app

import android.content.Context

class Settings(ctx: Context) {
    private val p = ctx.getSharedPreferences("playtoon", Context.MODE_PRIVATE)

    /** 10.0.2.2 is the host machine as seen from the Android emulator. */
    var serverUrl: String
        get() = p.getString("server_url", "http://10.0.2.2:8765")!!
        set(v) = p.edit().putString("server_url", v).apply()
    var aiProvider: String
        get() = p.getString("ai_provider", "auto")!!
        set(v) = p.edit().putString("ai_provider", v).apply()
    var aiModel: String
        get() = p.getString("ai_model", "")!!
        set(v) = p.edit().putString("ai_model", v).apply()
    var aiEffort: String
        get() = p.getString("ai_effort", "low")!!
        set(v) = p.edit().putString("ai_effort", v).apply()
    /** Spoken-language preference: auto-detect (default) or force en/fr/ar. */
    var language: String
        get() = p.getString("language", "auto")!!
        set(v) = p.edit().putString("language", v).apply()
    /** Topic terms that help speech recognition spell names and jargon (e.g. "Python, len(), Abuja"). */
    var asrVocabulary: String
        get() = p.getString("asr_vocabulary", "")!!
        set(v) = p.edit().putString("asr_vocabulary", v).apply()
    /** Empty = keep the original language (spec default: no automatic translation). */
    var translateTo: String
        get() = p.getString("translate_to", "")!!
        set(v) = p.edit().putString("translate_to", v).apply()
}
