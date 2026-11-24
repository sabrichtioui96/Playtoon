# Playtoon acceptance tests

Run finished 2026-11-24T01:50:09 (Python 3.12.10). Generated from `docs/acceptance_results.json` by `backend/tools/acceptance_report.py`.

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
- **Answers in these runs come from the offline answerer** (arithmetic + a small demo fact table), because no Anthropic credentials were configured. The Claude path (`reasoning.py`) is implemented but was not exercised by this run. For the harder set this means only *detection* was scored, not answer correctness.
- **CPU latency.** On this machine (CPU only), Whisper `small` takes ~1.8 s per spoken segment once the language is known (~3.4 s when it must be detected), `large-v3-turbo` ~10–15 s; OCR ~0.8 s per image. Claude's own response time comes on top of the pipeline numbers in the latency table.
- **One harder case needs the host vocabulary:** on default settings Whisper hears Python's `len` as "LUN" in the clean clip; entering the topic vocabulary (Settings) fixes it (`test_hard_audio_with_host_vocabulary`).
- **Test 10 uses an emulator** (Android 16 / API 36, x86_64) and an image upload as input; the in-app microphone and MediaProjection screen-capture flows were built but need a manual check on a device (they require interactive OS consent dialogs).

## 1. Question displayed as ordinary browser text

Outcome: **passed** in 0.01 s

```json
{
 "question": {
  "question_id": "q_e6c727a539de",
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
  "processing_ms": 625,
  "answer": "Saturn",
  "option_index": 1,
  "answer_provider": "offline"
 },
 "dom_updates_sent": 1,
 "screenshot_ocr": "Weekly quiz\nWelcome back! Read carefully.\nWhich planet has the largest number of moons?\nA) Jupiter\nB) Saturn\nC) Uranus\nD) Neptune\n\nHi! I am QuizBot. Let us warm up.\nWho wrote Hamlet? And in which country\nwas he born?\nShakespeare, England.\nCorrect! Next: what is the capital of Japan?\nA) Kyoto B) Osaka C) Tokyo D) Nagoya\nTokyo\nAnd what about Australia?"
}
```

## 2. Question embedded in an image

Outcome: **passed** in 2.73 s

```json
{
 "ocr_text": "Space Trivia - Round 2\nWhich planet has the largest number of moons?\nA) Jupiter\nB)Saturn\nC) Uranus\nD) Neptune",
 "question": {
  "question_id": "q_08ae4dadc97a",
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
  "processing_ms": 78,
  "answer": "Saturn",
  "option_index": 1,
  "answer_provider": "offline"
 },
 "math_ocr": "Math check:\nWhat is 12 x 7 + 5 = ?",
 "math": {
  "question_id": "q_e2704d75eb26",
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
  "processing_ms": 79,
  "answer": "89",
  "option_index": null,
  "answer_provider": "offline"
 }
}
```

## 3. Question displayed in a video frame

Outcome: **passed** in 6.33 s

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
   "question_id": "q_d7ef4fcd6a3e",
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
   "processing_ms": 2827,
   "answer": "Saturn",
   "option_index": 1,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_1ff5f642df66",
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
   "processing_ms": 2217,
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
   "question_id": "q_5b975fec0ca6",
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
   "processing_ms": 1031,
   "answer": "William Shakespeare",
   "option_index": null,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_2008fbba8518",
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
   "processing_ms": 1031,
   "answer": null,
   "option_index": null,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_29468d8f239a",
   "question_text": "what is the capital of Japan?",
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
   "processing_ms": 1015,
   "answer": "Tokyo",
   "option_index": 2,
   "answer_provider": "offline"
  },
  {
   "question_id": "q_64460723a31f",
   "question_text": "And what about Australia?",
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
   "processing_ms": 1046,
   "answer": "Canberra",
   "option_index": null,
   "answer_provider": "offline"
  }
 ],
 "ai_requests_total": 5
}
```

## 5. Spoken English question — `clean`

Outcome: **passed** in 13.77 s

```json
{
 "question": {
  "question_id": "q_d9c59d5914cc",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.734,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 63,
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
   "confidence": 0.722,
   "duration_s": 1.77,
   "asr_ms": 7958,
   "source": "mic:test"
  },
  {
   "session": "audio1",
   "text": "Which planet has the largest number of moons?",
   "language": "en",
   "language_prob": 1.0,
   "confidence": 0.734,
   "duration_s": 2.76,
   "asr_ms": 4199,
   "source": "mic:test"
  }
 ]
}
```

## 5. Spoken English question — `noisy`

Outcome: **passed** in 10.6 s

```json
{
 "question": {
  "question_id": "q_0495f651f20f",
  "question_text": "Which planet has the largest number of moons?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.794,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 93,
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
   "confidence": 0.794,
   "duration_s": 6.24,
   "asr_ms": 7288,
   "source": "mic:test"
  }
 ]
}
```

## 6. Spoken French question — `clean`

Outcome: **passed** in 13.74 s

```json
{
 "question": {
  "question_id": "q_839dfc84bf36",
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
  "processing_ms": 78,
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
   "confidence": 0.772,
   "duration_s": 1.89,
   "asr_ms": 7519,
   "source": "mic:test"
  },
  {
   "session": "audio3",
   "text": "Quelle est la capitale de l'Australie ?",
   "language": "fr",
   "language_prob": 0.998,
   "confidence": 0.845,
   "duration_s": 2.16,
   "asr_ms": 4497,
   "source": "mic:test"
  }
 ]
}
```

## 6. Spoken French question — `noisy`

Outcome: **passed** in 10.11 s

```json
{
 "question": {
  "question_id": "q_4ff8a9519d47",
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
  "processing_ms": 93,
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
   "language_prob": 0.993,
   "confidence": 0.844,
   "duration_s": 5.37,
   "asr_ms": 7220,
   "source": "mic:test"
  }
 ]
}
```

## 7. Spoken Arabic question — `clean`

Outcome: **passed** in 37.91 s

```json
{
 "question": {
  "question_id": "q_54d6d5ecd64b",
  "question_text": "ما هي عاصمة اليادان؟",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "ar",
  "options": [],
  "confidence": 0.791,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 93,
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
   "confidence": 0.828,
   "duration_s": 1.86,
   "asr_ms": 20031,
   "source": "mic:test"
  },
  {
   "session": "audio5",
   "text": "ما هي عاصمة اليادان؟",
   "language": "ar",
   "language_prob": 1.0,
   "confidence": 0.791,
   "duration_s": 2.19,
   "asr_ms": 16190,
   "source": "mic:test"
  }
 ]
}
```

## 7. Spoken Arabic question — `noisy`

Outcome: **passed** in 33.08 s

```json
{
 "question": {
  "question_id": "q_74e18b00b258",
  "question_text": "ما هي عاصمة اليابان؟",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "ar",
  "options": [],
  "confidence": 0.838,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 63,
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
   "language_prob": 0.989,
   "confidence": 0.873,
   "duration_s": 2.61,
   "asr_ms": 17684,
   "source": "mic:test"
  },
  {
   "session": "audio6",
   "text": "ما هي عاصمة اليابان؟",
   "language": "ar",
   "language_prob": 0.989,
   "confidence": 0.841,
   "duration_s": 1.86,
   "asr_ms": 13744,
   "source": "mic:test"
  }
 ]
}
```

## 8. Audio and text presented simultaneously

Outcome: **passed** in 15.93 s

```json
{
 "question": {
  "question_id": "q_8c99cbf877ee",
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
  "processing_ms": 62,
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

Outcome: **passed** in 6.12 s

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

Outcome: **passed** in 36.67 s

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

Outcome: **passed** in 33.45 s

```json
{
 "paused": {
  "question_id": "q_91b3fb7d77f1",
  "question_text": "Which river is the longest in Africa?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.743,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 77,
  "answer": null,
  "option_index": null,
  "answer_provider": "offline"
 },
 "multi_sentence": {
  "question_id": "q_1340d22d39bc",
  "question_text": "A train leaves Paris at 3 p.m. travelling at 120 km per hour. How far has it traveled by 5pm?",
  "source": [
   "audio"
  ],
  "channels": [
   "audio"
  ],
  "language": "en",
  "options": [],
  "confidence": 0.679,
  "status": "answered",
  "revision": 0,
  "discrepancies": [],
  "processing_ms": 108,
  "answer": null,
  "option_index": null,
  "answer_provider": "offline"
 },
 "audio_questions": 2
}
```


# Harder question set (English + French)

**34/35 passed.** Cases are defined in `backend/tests/hard_cases.py`; detection is scored on every run, answer correctness only when Claude is the answerer (`answer_correct` is `null` with the offline answerer).

| Case | Result | Detected question | Options |
|---|---|---|---|
| `image[img_fx]` | passed | If f(x) = 3x² - 2x + 1, what is f(4)? | 41, 43, 45, 49 |
| `image[img_word_problem]` | passed | A shop sells pens at $1.20 each. Mia buys 15 pens and pays with a $20 bill. How much change does she receive? | $0.00, $2.00, $2.50, $3.00 |
| `image[img_lookalike]` | passed | Which fraction is equal to 0.375? | 3/8, 3/5, 5/8, 8/3 |
| `image[img_numbered]` | passed | Which Chinese dynasty built most of the wall that stands today? | Han, Ming, Qin, Tang |
| `image[img_true_false]` | passed | True or False: Light travels faster than sound in air. | True, False |
| `image[img_fill_blank]` | passed | The chemical symbol for gold is ____. | - |
| `image[img_dark_small]` | passed | In which year did the Berlin Wall fall? | 1987, 1989, 1991, 1993 |
| `image[img_percent]` | passed | A jacket costs $80. It is discounted by 25%, then the sale price is increased by 1o%. What is the final price? | $60, $66, $68, $72 |
| `image[img_fr_history]` | passed | En quelle annee la Revolution francaise a-t-elle commence ? | 1776, 1789, 1799, 1815 |
| `image[img_fr_math]` | passed | Combien font 7 x 8 - 6 ? | - |
| `image[img_fr_word]` | passed | Un train part a 14 h 30 et roule pendant 2 h 45. A quelle heure arrive-t-il ? | 16 h 45, 17 h 05, 17 h 15, 17 h 45 |
| `image[img_fr_accents]` | passed | Quel élement chimique a pour symbole 《 Fe 》 ? | Le fluor, Le fer, Le francium, Le fermium |
| `chat[chat_followup_chain]` | passed | Which country has the largest population in Africa?; And what is its capital city?; How many states does it have? | - |
| `chat[chat_split_message]` | passed | What is the boiling point of water at sea level in degrees Fahrenheit? | - |
| `chat[chat_numbered_options]` | passed | Which of these is a prime number? | - |
| `chat[chat_fr_followup]` | passed | Quel est le plus long fleuve de France ?; Et le deuxième ? | - |
| `chat[chat_fr_options_inline]` | passed | quelle planète est surnommée la planète rouge ? | - |
| `chat[chat_not_questions]` | passed | - | - |
| `audio[aud_en_date-clean]` | passed | In 1969, Apollo 11 landed on the moon. Which astronaut was the second person to walk on its surface? | - |
| `audio[aud_en_date-noisy]` | passed | In 1969, Apollo 11 landed on the moon. Which astronaut was the second person to walk on its surface? | - |
| `audio[aud_en_percent-clean]` | passed | What is 15% of 240? | - |
| `audio[aud_en_percent-noisy]` | passed | What is 15% of 240? | - |
| `audio[aud_en_spoken_options-clean]` | passed | Which gas do plants absorb from the air? | Oxygen, Nitrogen, Carbon dioxide, Helium |
| `audio[aud_en_spoken_options-noisy]` | passed | Which gas-due plants absorb from the air? | Oxygen, Nitrogen, Carbon dioxide, Helium |
| `audio[aud_en_technical-clean]` | failed | In Python, what does the LUN function return when called on the string hello world? | - |
| `audio[aud_en_technical-noisy]` | passed | In Python, what does the LEN function return when called on the string hello world? | - |
| `audio[aud_fr_time-clean]` | passed | Un train part à 14h30 et roule pendant 2h45. À quelle heure arrive-t-il ? | - |
| `audio[aud_fr_time-noisy]` | passed | Un train part à 14h30 et roule pendant 2h41. À quelle heure arrive Théïne ? | - |
| `audio[aud_fr_hexagon-clean]` | passed | Combien de côtés possède un hexagone ? | - |
| `audio[aud_fr_hexagon-noisy]` | passed | Combien de côtés possède un hexagone ? | - |
| `audio[aud_fr_spoken_options-clean]` | passed | Quel est le plus grand océan du monde ? | L'Atlantique, L'Indien, Le Pacifique |
| `audio[aud_fr_spoken_options-noisy]` | passed | Quel est le plus grand océan du monde ? | L'Atlantique, L'Indien, Le Pacifique |
| `audio[aud_fr_names-clean]` | passed | Qui a écrit le roman Les Misérables, publié en 1862 ? | - |
| `audio[aud_fr_names-noisy]` | passed | Qui a écrit le roman Les Misérables, publié en 1862. | - |
| `audio_with_host_vocabulary` | passed | In Python, what does the len function return when called on the string hello world? | - |

### test_hard_audio[aud_en_technical-clean] (failed)
```
f variant == "noisy" else "")
        stream_wav(HARD / f"{name}.wav", speed=3.0)
        q = wait_for(lambda: next((x for x in qs(client) if "audio" in x["source"] and x["status"] == "answered"), None), 90)
        tr = [e["data"]["text"] for e in events.of("transcript.final")]
        assert q, f"no question; transcripts={tr}"
        nq = N(q["question_text"])
        missing = [k for k in case["keywords"] if N(k) not in nq and not (extract_numbers(k) and set(extract_numbers(k)) <= set(extract_numbers(q["question_text"])))]
        sim = fuzz.token_set_ratio(N(case["question"]), nq)
        ok_ans = answer_ok(q, case["answer"])
        record(f"test_hard_audio[{case['id']}-{variant}]", transcripts=tr, detected=q["question_text"], similarity=sim,
               options=q["options"], language=q["language"], answer=(q["answer"] or {}).get("suggested_answer"),
               answer_correct=ok_ans)
        assert q["language"] == case["lang"]
>       assert not missing, (missing, q["question_text"])
E       AssertionError: (['len'], 'In Python, what does the LUN function return when called on the string hello world?')
E       assert not ['len']

tests\test_hard.py:112: AssertionError
```

# Latency (question shown / speech ended -> answer delivered)

Pipeline latency measured by `backend/tools/latency_bench.py` with the offline answerer (model time excluded; add Claude's response time on top). Median of 3 runs, seconds.

| Input | baseline | speedup1 | final |
|---|---|---|---|
| browser_text | 1.262 | 0.642 | 0.633 |
| chat_message | 1.237 | 0.114 | 0.088 |
| image_upload | 2.7 | 1.664 | 0.976 |
| speech_en | 6.46 | 2.524 | 2.901 |
| speech_fr | 7.173 | 3.218 | 6.35 |