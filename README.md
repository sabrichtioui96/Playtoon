# Playtoon

Multimodal question-detection engine: recognizes questions from browser text, images, video frames,
chatbot conversations and speech (English, French, Arabic), fuses duplicate detections across
modalities, and sends each question once to an AI model for a suggested answer.

> **Status:** all 10 acceptance tests from the spec pass (see [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md),
> including its *Known limitations* section).

## Layout

| Path | What |
|---|---|
| `backend/playtoon/text_utils.py` | Language ID (en/fr/ar), question + multiple-choice parsing, completeness checks |
| `backend/playtoon/ocr.py`, `vision.py` | OpenCV preprocessing, OCR (RapidOCR / optional Tesseract), video frame-change detection, text-region (band) tracking, frame dedup |
| `backend/playtoon/audio.py` | Noise gate + WebRTC VAD endpointing, Whisper transcription (original language, no translation), multi-sentence / paused-question assembly |
| `backend/playtoon/chat.py` | Chatbot message tracking with short context for follow-up questions |
| `backend/playtoon/fusion.py` | Central question manager: merge, discrepancy recording, settle window, one AI request per question |
| `backend/playtoon/reasoning.py` | Claude answerer (structured JSON output) with an offline fallback |
| `backend/playtoon/engine.py`, `server.py` | Async pipeline, FastAPI REST ingest + WebSocket event stream (`/ws/client`) and mic audio (`/ws/audio`) |
| `browser-extension/` | MV3 extension: reads visible text and chatbot messages on tabs the user explicitly enables |
| `backend/tests/` | Unit tests, acceptance tests (incl. Android via adb), fixtures (`tools/make_fixtures.py` regenerates them) |

## Run

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/python -m pip install -r requirements.txt
../.venv/Scripts/python -m playtoon.server        # http://0.0.0.0:8765
```

AI answers use Claude when `ANTHROPIC_API_KEY` (or an `ant auth login` profile) is available;
otherwise an offline answerer handles arithmetic and a few demo facts. Env vars:
`PLAYTOON_AI_PROVIDER` (auto|anthropic|offline), `PLAYTOON_AI_MODEL`, `PLAYTOON_AI_EFFORT`,
`PLAYTOON_ASR_MODEL` (default `small`), `PLAYTOON_ASR_MODEL_AR` (e.g. `large-v3-turbo`).

## Tests

```bash
cd backend
../.venv/Scripts/python -m pytest tests/test_units.py        # fast, passing
../.venv/Scripts/python -m pytest tests/test_acceptance.py tests/test_android.py   # starts the server; test 10 needs an emulator + built APK
../.venv/Scripts/python tools/acceptance_report.py            # regenerates docs/ACCEPTANCE.md
```

## Android app

`android/` is a Jetpack Compose app: live question feed, audio transcription panel, history,
connection status, AI + language settings, manual screenshot import, microphone streaming
(foreground service) and screen capture (MediaProjection), with visible "MIC ON" / "SCREEN ON"
indicators in addition to Android's own.

```bash
cd android
gradlew.bat assembleDebug            # needs JDK 17+ (Android Studio's jbr works) and the Android SDK
adb install -r app/build/outputs/apk/debug/app-debug.apk
```
The default engine URL is `http://10.0.2.2:8765` (the host from the emulator); change it in Settings.

## Status

All acceptance tests pass: `docs/ACCEPTANCE.md` (generated from the last run) lists evidence per test and
known limitations. Arabic speech uses Whisper `large-v3-turbo` (`PLAYTOON_ASR_MODEL_AR`) and is still not
word-perfect; the test runs used the offline answerer (no Anthropic credentials configured).
