"""Render docs/ACCEPTANCE.md from docs/acceptance_results.json (written by the pytest run)."""
from __future__ import annotations

import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"

SPEC = [
    ("test_01_browser_text", "1. Question displayed as ordinary browser text"),
    ("test_02_image_question", "2. Question embedded in an image"),
    ("test_03_video_frames", "3. Question displayed in a video frame"),
    ("test_04_chatbot_conversation", "4. Question in a chatbot conversation"),
    ("test_05_spoken_english", "5. Spoken English question"),
    ("test_06_spoken_french", "6. Spoken French question"),
    ("test_07_spoken_arabic", "7. Spoken Arabic question"),
    ("test_08_simultaneous_audio_and_visual", "8. Audio and text presented simultaneously"),
    ("test_09_no_duplicate_submission", "9. Same question not submitted twice"),
    ("test_10_android_displays_result", "10. Result displayed in the Android app"),
]
EXTRA = [("test_05b_speech_completeness", "Supporting: paused / multi-sentence / non-question speech")]


def rows(results: dict, key: str) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in results.items() if k == key or k.startswith(key + "[")]


def fmt(v) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1)


def main() -> None:
    res = json.loads((DOCS / "acceptance_results.json").read_text(encoding="utf-8"))
    meta = res.get("_meta", {})
    out = ["# Playtoon acceptance tests", "",
           f"Run finished {meta.get('finished', '?')} (Python {meta.get('python', '?')}). Generated from "
           "`docs/acceptance_results.json` by `backend/tools/acceptance_report.py`.", "",
           "Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_acceptance.py tests/test_android.py -v`", "",
           "| Spec test | Result | Runs |", "|---|---|---|"]
    for key, title in SPEC + EXTRA:
        rs = rows(res, key)
        if not rs:
            out.append(f"| {title} | NOT RUN | - |")
            continue
        outcomes = [v.get("outcome", "?") for _, v in rs]
        status = "PASS" if all(o == "passed" for o in outcomes) else ("SKIPPED" if all(o == "skipped" for o in outcomes) else "FAIL")
        out.append(f"| {title} | **{status}** | {', '.join(f'{k.split('[')[-1].rstrip(']') if '[' in k else 'run'}: {v.get('outcome')}' for k, v in rs)} |")
    out += ["", "## Known limitations (read before relying on the PASS marks)", "",
            "- **Arabic transcription is not word-perfect.** On the clean Arabic clip, Whisper `large-v3-turbo` "
            "hears \"اليادان\" instead of \"اليابان\" (Japan); one letter is wrong. Test 7 passes because it "
            "accepts ≥ 85 % similarity to the reference and checks the language, completeness and the answer path. "
            "The noisy clip transcribes exactly. `small` (used for English/French) also got \"عاصمة\" wrong, which is why "
            "Arabic is routed to turbo (`PLAYTOON_ASR_MODEL_AR`).",
            "- **Test speech is synthetic.** English/French clips are Windows SAPI voices, Arabic is an edge-tts neural "
            "voice; noisy variants add synthetic babble + 50 Hz hum at ~10 dB SNR. Real microphones, accents and rooms "
            "were not tested.",
            "- **Answers in these runs come from the offline answerer** (arithmetic + a small demo fact table), because "
            "no Anthropic credentials were configured. The Claude path (`reasoning.py`) is implemented but was not "
            "exercised by this run.",
            "- **CPU latency.** On this machine (CPU only), Whisper takes ~3–6 s per spoken segment (`small`) and "
            "~10–15 s (`large-v3-turbo`); OCR ~1–2 s per image. A GPU is recommended for real-time use.",
            "- **Test 10 uses an emulator** (Android 16 / API 36, x86_64) and an image upload as input; the in-app "
            "microphone and MediaProjection screen-capture flows were built but need a manual check on a device "
            "(they require interactive OS consent dialogs).",
            ""]
    for key, title in SPEC + EXTRA:
        for k, v in rows(res, key):
            out += [f"## {title}" + (f" — `{k.split('[', 1)[1].rstrip(']')}`" if "[" in k else ""), "",
                    f"Outcome: **{v.get('outcome')}** in {v.get('duration_s', '?')} s", ""]
            ev = {x: y for x, y in v.items() if x not in ("outcome", "duration_s", "failure")}
            if ev:
                out += ["```json", fmt(ev), "```", ""]
            if v.get("failure"):
                out += ["Failure:", "```", v["failure"], "```", ""]
            if key == "test_10_android_displays_result" and v.get("screenshot"):
                out += [f"![Android result]({Path(v['screenshot']).name})", ""]
    (DOCS / "ACCEPTANCE.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote", DOCS / "ACCEPTANCE.md")


if __name__ == "__main__":
    main()
