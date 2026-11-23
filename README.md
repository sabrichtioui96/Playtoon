# Playtoon

Multimodal question-detection engine: recognizes questions from browser text, images, video frames,
chatbot conversations and speech (English, French, Arabic), fuses duplicate detections across
modalities, and sends each question once to an AI model for a suggested answer.

> **Status: work in progress.** The Python backend and the browser extension are written; the
> Android (Jetpack Compose) app and the full acceptance-test run are not done yet. See
> "Status" below.

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
| `backend/tests/` | Unit tests, acceptance tests, fixtures (`tools/make_fixtures.py` regenerates them) |

## Run

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/python -m pip install -r requirements.txt
../.venv/Scripts/python -m playtoon.server        # http://0.0.0.0:8765
```

AI answers use Claude when `ANTHROPIC_API_KEY` (or an `ant auth login` profile) is available;
otherwise an offline answerer handles arithmetic and a few demo facts. Env vars:
`PLAYTOON_AI_PROVIDER` (auto|anthropic|offline), `PLAYTOON_AI_MODEL`, `PLAYTOON_AI_EFFORT`,
`PLAYTOON_ASR_MODEL` (default `small`).

## Tests

```bash
cd backend
../.venv/Scripts/python -m pytest tests/test_units.py        # fast, passing
../.venv/Scripts/python -m pytest tests/test_acceptance.py   # starts the server; not yet run end-to-end
```

## Status

Done: backend modules, browser extension, fixtures, unit tests (8/8 pass). Smoke runs: image OCR,
video (22 OCR calls for 65 sampled frames), English/French speech incl. noisy audio.

Open:
- Arabic speech with Whisper `small` mis-transcribes words; evaluating `large-v3-turbo`.
- Android app (Compose: live feed, transcription panel, history, connection status, AI/language settings, screenshot import, mic + MediaProjection capture with visible indicators).
- Full acceptance-test run (spec tests 1–10) and `docs/ACCEPTANCE.md`.
