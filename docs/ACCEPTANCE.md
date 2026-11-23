# Playtoon acceptance tests

Run finished 2026-11-23T22:05:46 (Python 3.12.10). Generated from `docs/acceptance_results.json` by `backend/tools/acceptance_report.py`.

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_acceptance.py tests/test_android.py -v`

| Spec test | Result | Runs |
|---|---|---|
| 1. Question displayed as ordinary browser text | **PASS** | run: passed |
| 2. Question embedded in an image | **PASS** | run: passed |
| 3. Question displayed in a video frame | **PASS** | run: passed |
| 4. Question in a chatbot conversation | **PASS** | run: passed |
| 5. Spoken English question | **PASS** | clean: passed, noisy: passed |
| 6. Spoken French question | **PASS** | clean: passed, noisy: passed |
| 7. Spoken Arabic question | **PASS** | clean: passed, noisy: passed |
| 8. Audio and text presented simultaneously | **PASS** | run: passed |
| 9. Same question not submitted twice | **PASS** | run: passed |
| 10. Result displayed in the Android app | **PASS** | run: passed |
| Supporting: paused / multi-sentence / non-question speech | **PASS** | run: passed |

## Known limitations (read before relying on the PASS marks)

- **Arabic transcription is not word-perfect.** On the clean Arabic clip, Whisper `large-v3-turbo` hears "اليادان" instead of "اليابان" (Japan); one letter is wrong. Test 7 passes because it accepts ≥ 85 % similarity to the reference and checks the language, completeness and the answer path. The noisy clip transcribes exactly. `small` (used for English/French) also got "عاصمة" wrong, which is why Arabic is routed to turbo (`PLAYTOON_ASR_MODEL_AR`).
- **Test speech is synthetic.** English/French clips are Windows SAPI voices, Arabic is an edge-tts neural voice; noisy variants add synthetic babble + 50 Hz hum at ~10 dB SNR. Real microphones, accents and rooms were not tested.
- **Answers in these runs come from the offline answerer** (arithmetic + a small demo fact table), because no Anthropic credentials were configured. The Claude path (`reasoning.py`) is implemented but was not exercised by this run.
- **CPU latency.** On this machine (CPU only), Whisper takes ~3–6 s per spoken segment (`small`) and ~10–15 s (`large-v3-turbo`); OCR ~1–2 s per image. A GPU is recommended for real-time use.
- **Test 10 uses an emulator** (Android 16 / API 36, x86_64) and an image upload as input; the in-app microphone and MediaProjection screen-capture flows were built but need a manual check on a device (they require interactive OS consent dialogs).

## 1. Question displayed as ordinary browser text

Outcome: **passed** in 0.0 s

```json
{
 "question": {
  "question_id": "q_660436bda9f7",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "visual"
  ],
  "channels": [
   "browser",
   "visual"
  ],
  "language": "en",
  "options": [
   "Jupiter",
   "Saturn",
   "Uranus",
   "Neptune"
  ],
  "confidence": 0.99,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1280,
  "answer": "Saturn",
  "option_index": 1,
  "answer_provider": "offline"
 },
 "dom_updates_sent": 1,
 "screenshot_ocr": "Weekly quiz\nWelcome back! Read carefully.\nWhich planet has the largest number of moons?\nA) Jupiter\nB) Saturn\nC) Uranus\nD) Neptune\n\nHi! I am QuizBot. Let us warm up.\nWho wrote Hamlet? And in which country\nwas he born?\nShakespeare, England.\nCorrect! Next: what is the capital of Japan?\nA) Kyoto B) Osaka C) Tokyo D) Nagoya\nTokyo\nAnd what about Australia?"
}
```

## 2. Question embedded in an image

Outcome: **passed** in 6.33 s

```json
{
 "ocr_text": "Space Trivia - Round 2\nWhich planet has the largest number of moons?\nA) Jupiter\nB)Saturn\nC) Uranus\nD) Neptune",
 "question": {
  "question_id": "q_f14e2fc7cabb",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "visual"
  ],
  "channels": [
   "visual"
  ],
  "language": "en",
  "options": [
   "Jupiter",
   "Saturn",
   "Uranus",
   "Neptune"
  ],
  "confidence": 0.981,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1265,
  "answer": "Saturn",
  "option_index": 1,
  "answer_provider": "offline"
 },
 "math_ocr": "Math check:\nWhat is 12 x 7 + 5 = ?",
 "math": {
  "question_id": "q_ab30cf2fe122",
  "question_text": "What is 12 x 7 + 5 = ?",
  "source": [
   "visual"
  ],
  "channels": [
   "visual"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.944,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1266,
  "answer": "89",
  "option_index": null,
  "answer_provider": "offline"
 }
}
```

## 3. Question displayed in a video frame

Outcome: **passed** in 14.63 s

```json
{
 "job_stats": {
  "frames_seen": 65,
  "skipped_static": 0,
  "skipped_in_motion": 47,
  "dedup_hits": 0,
  "ocr_full": 3,
  "ocr_region": 22,
  "text_changes": 17,
  "ocr_calls": 25
 },
 "video_frames_total": 325,
 "questions": [
  {
   "question_id": "q_64099460c8a5",
   "question_text": "Which planet has the largest number of moons?",
   "source": [
    "visual"
   ],
   "channels": [
    "visual"
   ],
   "language": "en",
   "options": [
    "Jupiter",
    "Saturn",
    "Uranus",
    "Neptune"
   ],
   "confidence": 0.99,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 6797,
   "answer": "Saturn",
   "option_index": 1,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_5cde85be5ed0",
   "question_text": "What is the capital of Australia?",
   "source": [
    "visual"
   ],
   "channels": [
    "visual"
   ],
   "language": "en",
   "options": [
    "Sydney",
    "Melbourne",
    "Canberra",
    "Perth"
   ],
   "confidence": 0.989,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 4406,
   "answer": "Canberra",
   "option_index": 2,
   "answer_provider": "offline"
  }
 ],
 "ai_requests": 2
}
```

## 4. Question in a chatbot conversation

Outcome: **passed** in 0.0 s

```json
{
 "questions": [
  {
   "question_id": "q_9d82aa9f0b23",
   "question_text": "Who wrote Hamlet?",
   "source": [
    "visual"
   ],
   "channels": [
    "chat",
    "visual"
   ],
   "language": "en",
   "options": [],
   "confidence": 0.988,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 1233,
   "answer": "William Shakespeare",
   "option_index": null,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_e6418cfddd85",
   "question_text": "And in which country was he born?",
   "source": [
    "visual"
   ],
   "channels": [
    "chat",
    "visual"
   ],
   "language": "en",
   "options": [],
   "confidence": 0.988,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 1233,
   "answer": null,
   "option_index": null,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_ae7d0ab855f1",
   "question_text": "Next: what is the capital of Japan?",
   "source": [
    "visual"
   ],
   "channels": [
    "chat",
    "visual"
   ],
   "language": "en",
   "options": [
    "Kyoto",
    "Osaka",
    "Tokyo",
    "Nagoya"
   ],
   "confidence": 0.988,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 1281,
   "answer": "Tokyo",
   "option_index": 2,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_72a1db37adc1",
   "question_text": "Tokyo And what about Australia?",
   "source": [
    "visual"
   ],
   "channels": [
    "chat",
    "visual"
   ],
   "language": "en",
   "options": [],
   "confidence": 0.988,
   "status": "answered",
   "revision": 0,
   "discrepancies": [],
   "processing_ms": 1281,
   "answer": "Canberra",
   "option_index": null,
   "answer_provider": "offline"
  }
 ],
 "ai_requests_total": 5
}
```

## 5. Spoken English question — `clean`

Outcome: **passed** in 10.55 s

```json
{
 "question": {
  "question_id": "q_bae403f0e570",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.727,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1266,
  "answer": "Saturn",
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 100.0,
 "transcripts": [
  {
   "session": "audio1",
   "text": "Here is a space question.",
   "language": "en",
   "language_prob": 1.0,
   "confidence": 0.727,
   "duration_s": 1.77,
   "asr_ms": 3845,
   "source": "mic:test"
  },
  {
   "session": "audio1",
   "text": "Which planet has the largest number of moons?",
   "language": "en",
   "language_prob": 1.0,
   "confidence": 0.727,
   "duration_s": 2.76,
   "asr_ms": 4005,
   "source": "mic:test"
  }
 ]
}
```

## 5. Spoken English question — `noisy`

Outcome: **passed** in 8.31 s

```json
{
 "question": {
  "question_id": "q_671e9fb0dd33",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.798,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1204,
  "answer": "Saturn",
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 100.0,
 "transcripts": [
  {
   "session": "audio2",
   "text": "Here is a space question. Which planet has the largest number of moons?",
   "language": "en",
   "language_prob": 1.0,
   "confidence": 0.799,
   "duration_s": 6.24,
   "asr_ms": 3940,
   "source": "mic:test"
  }
 ]
}
```

## 6. Spoken French question — `clean`

Outcome: **passed** in 11.13 s

```json
{
 "question": {
  "question_id": "q_133c333873e8",
  "question_text": "Quelle est la capitale de l'Australie ?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "fr",
  "options": [],
  "confidence": 0.844,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1250,
  "answer": "Canberra",
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 100.0,
 "transcripts": [
  {
   "session": "audio3",
   "text": "Question de géographie.",
   "language": "fr",
   "language_prob": 0.998,
   "confidence": 0.766,
   "duration_s": 1.89,
   "asr_ms": 4031,
   "source": "mic:test"
  },
  {
   "session": "audio3",
   "text": "Quelle est la capitale de l'Australie ?",
   "language": "fr",
   "language_prob": 0.993,
   "confidence": 0.846,
   "duration_s": 2.16,
   "asr_ms": 4337,
   "source": "mic:test"
  }
 ]
}
```

## 6. Spoken French question — `noisy`

Outcome: **passed** in 8.19 s

```json
{
 "question": {
  "question_id": "q_78d0803be74b",
  "question_text": "Quelle est la capitale de l'Australie ?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "fr",
  "options": [],
  "confidence": 0.842,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1218,
  "answer": "Canberra",
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 100.0,
 "transcripts": [
  {
   "session": "audio4",
   "text": "Question de géographie. Quelle est la capitale de l'Australie ?",
   "language": "fr",
   "language_prob": 0.994,
   "confidence": 0.844,
   "duration_s": 5.37,
   "asr_ms": 4175,
   "source": "mic:test"
  }
 ]
}
```

## 7. Spoken Arabic question — `clean`

Outcome: **passed** in 23.55 s

```json
{
 "question": {
  "question_id": "q_3f1207db570d",
  "question_text": "ما هي عاصمة اليادان؟",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "ar",
  "options": [],
  "confidence": 0.796,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1202,
  "answer": null,
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 94.73684210526316,
 "transcripts": [
  {
   "session": "audio5",
   "text": "سؤال في الجغرافيا",
   "language": "ar",
   "language_prob": 1.0,
   "confidence": 0.83,
   "duration_s": 1.86,
   "asr_ms": 10313,
   "source": "mic:test"
  },
  {
   "session": "audio5",
   "text": "ما هي عاصمة اليادان؟",
   "language": "ar",
   "language_prob": 0.998,
   "confidence": 0.797,
   "duration_s": 2.19,
   "asr_ms": 10502,
   "source": "mic:test"
  }
 ]
}
```

## 7. Spoken Arabic question — `noisy`

Outcome: **passed** in 23.64 s

```json
{
 "question": {
  "question_id": "q_61daadfb0176",
  "question_text": "ما هي عاصمة اليابان؟",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "ar",
  "options": [],
  "confidence": 0.84,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1264,
  "answer": "طوكيو",
  "option_index": null,
  "answer_provider": "offline"
 },
 "similarity": 100.0,
 "transcripts": [
  {
   "session": "audio6",
   "text": "سؤال في الجغرافية",
   "language": "ar",
   "language_prob": 0.986,
   "confidence": 0.872,
   "duration_s": 2.61,
   "asr_ms": 9981,
   "source": "mic:test"
  },
  {
   "session": "audio6",
   "text": "ما هي عاصمة اليابان؟",
   "language": "ar",
   "language_prob": 0.99,
   "confidence": 0.844,
   "duration_s": 1.86,
   "asr_ms": 10725,
   "source": "mic:test"
  }
 ]
}
```

## 8. Audio and text presented simultaneously

Outcome: **passed** in 11.79 s

```json
{
 "question": {
  "question_id": "q_cf91c81e3068",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "visual",
   "audio"
  ],
  "channels": [
   "audio",
   "visual"
  ],
  "language": "en",
  "options": [
   "Jupiter",
   "Saturn",
   "Uranus",
   "Neptune"
  ],
  "confidence": 0.995,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 5015,
  "answer": "Saturn",
  "option_index": 1,
  "answer_provider": "offline"
 },
 "variants": {
  "visual": "Which planet has the largest number of moons?",
  "audio": "Which planet has the largest number of moons?"
 },
 "ai_requests": 1
}
```

## 9. Same question not submitted twice

Outcome: **passed** in 9.92 s

```json
{
 "detections_submitted": 5,
 "questions": 1,
 "ai_requests": 1,
 "suppressed_duplicates": 4,
 "channels": [
  "browser",
  "chat",
  "visual"
 ]
}
```

## 10. Result displayed in the Android app

Outcome: **passed** in 15.87 s

```json
{
 "ui_text": "Source: visual | Language: English | answered | Which planet has the largest number of moons? | A) Jupiter | B) Saturn  ✓ | C) Uranus | D) Neptune | Suggested answer: Saturn | Confidence: 60%  ·  Detection: 98% | Saturn has the most confirmed moons (over 270 as of 2025). (offline demo knowledge) | Processing: 1203 ms (model 0 ms) · offline | Playtoon | Connected | Live | Audio | History | Settings",
 "screenshot": "docs/android_test10.png",
 "device": "sdk_gphone64_x86_64",
 "sdk": "36"
}
```

![Android result](android_test10.png)

## Supporting: paused / multi-sentence / non-question speech

Outcome: **passed** in 32.29 s

```json
{
 "paused": {
  "question_id": "q_155fc30a13a9",
  "question_text": "Which river is the longest in Africa?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.74,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1202,
  "answer": null,
  "option_index": null,
  "answer_provider": "offline"
 },
 "multi_sentence": {
  "question_id": "q_237b66cf89c5",
  "question_text": "A train leaves Paris at 3 p.m. travelling at 120 km per hour. How far has it traveled by 5pm?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.672,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 1296,
  "answer": null,
  "option_index": null,
  "answer_provider": "offline"
 },
 "audio_questions": 2
}
```
