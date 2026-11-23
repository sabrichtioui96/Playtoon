"""Generate acceptance-test fixtures into backend/tests/fixtures.

  images : question embedded in a photo-like image, a math image
  video  : animated background, question typed progressively, options appearing one by one,
           then a second question (exercises frame-change detection + region tracking)
  audio  : spoken questions in en / fr (Windows SAPI voices, offline) and ar (edge-tts neural voice),
           plus noisy variants (babble + hum at ~10 dB SNR) and a paused two-part question
"""
from __future__ import annotations

import asyncio
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
SR = 16000


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


# ----------------------------------------------------------------------------- images
def make_images():
    rng = np.random.default_rng(1)
    w, h = 1280, 720
    # "photo-like" textured background with a quiz card
    base = (rng.normal(0, 1, (h // 8, w // 8, 3)) * 40 + np.array([90, 120, 160])).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(base).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((140, 110, 1140, 610), 28, fill=(255, 255, 255, 225))
    d.text((190, 150), "Space Trivia - Round 2", font=font(30, True), fill=(200, 60, 60))
    d.text((190, 215), "Which planet has the largest number of moons?", font=font(40, True), fill=(20, 20, 30))
    for i, (k, v) in enumerate(zip("ABCD", ["Jupiter", "Saturn", "Uranus", "Neptune"])):
        y = 310 + i * 68
        d.rounded_rectangle((190, y, 700, y + 54), 12, fill=(235, 240, 250, 255), outline=(150, 160, 190))
        d.text((210, y + 6), f"{k}) {v}", font=font(32), fill=(30, 30, 60))
    img.save(OUT / "image_question.png")
    # jpeg re-compression to simulate shared screenshots
    img.convert("RGB").save(OUT / "image_question.jpg", quality=70)

    m = Image.new("RGB", (900, 400), (250, 250, 245))
    d = ImageDraw.Draw(m)
    d.text((60, 60), "Math check:", font=font(36, True), fill=(10, 90, 160))
    d.text((60, 150), "What is 12 × 7 + 5 = ?", font=font(52), fill=(0, 0, 0))
    m.save(OUT / "image_math.png")


# ----------------------------------------------------------------------------- video
def draw_frame(t: float, w=1280, h=720) -> np.ndarray:
    # animated gradient + moving circle in the top banner (motion that is NOT text)
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    r = (40 + 30 * np.sin(2 * math.pi * (x + t * 0.05))) * np.ones_like(y)
    g = 60 + 40 * y + 0 * x
    b = 110 + 30 * np.cos(2 * math.pi * (y + t * 0.05)) + 0 * x
    arr = np.dstack([r, g, b]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img, "RGBA")
    cx = int(100 + (t * 180) % (w - 200))
    d.ellipse((cx - 30, 30, cx + 30, 90), fill=(255, 200, 0, 255))
    d.rounded_rectangle((120, 150, 1160, 660), 24, fill=(255, 255, 255, 235))

    q1 = "Which planet has the largest number of moons?"
    opts1 = ["A) Jupiter", "B) Saturn", "C) Uranus", "D) Neptune"]
    q2 = "What is the capital of Australia?"
    opts2 = ["A) Sydney", "B) Melbourne", "C) Canberra", "D) Perth"]
    if t < 7.0:
        q, opts, t0 = q1, opts1, 0.5
    else:
        q, opts, t0 = q2, opts2, 7.5
    # typewriter: 12 chars / second
    n = int(max(0, t - t0) * 12)
    d.text((170, 190), q[:n], font=font(38, True), fill=(20, 20, 30))
    t_opts = t0 + len(q) / 12 + 0.5
    for i, o in enumerate(opts):
        ti = t_opts + i * 0.6
        if t >= ti:
            alpha = int(min(1.0, (t - ti) / 0.3) * 255)     # fade-in animation
            yy = 280 + i * 80
            d.rounded_rectangle((170, yy, 640, yy + 60), 12, fill=(230, 236, 250, alpha))
            d.text((190, yy + 8), o, font=font(32), fill=(30, 30, 60, alpha))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def make_video(seconds=13.0, fps=25):
    path = str(OUT / "video_quiz.mp4")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (1280, 720))
    for i in range(int(seconds * fps)):
        vw.write(draw_frame(i / fps))
    vw.release()


# ----------------------------------------------------------------------------- audio
def write_wav(path: Path, audio: np.ndarray, sr=SR):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def read_any(path: Path) -> np.ndarray:
    from faster_whisper.audio import decode_audio
    return decode_audio(str(path), sampling_rate=SR)


def sapi(text: str, voice_culture: str, out: Path):
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq '{voice_culture}' }} | Select-Object -First 1
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{out}', $fmt)
$s.Speak([System.IO.File]::ReadAllText('{out}.txt', [System.Text.Encoding]::UTF8))
$s.Dispose()
"""
    Path(str(out) + ".txt").write_text(text, encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    os.unlink(str(out) + ".txt")


async def edge(text: str, voice: str, out: Path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(out))


def pad(a: np.ndarray, before=0.8, after=1.2):
    return np.concatenate([np.zeros(int(before * SR)), a, np.zeros(int(after * SR))]).astype(np.float32)


def add_noise(a: np.ndarray, snr_db=10.0, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(a)
    t = np.arange(n) / SR
    # babble-ish noise: band-limited noise with slow amplitude modulation + 50 Hz mains hum
    white = rng.normal(0, 1, n)
    k = np.ones(8) / 8
    babble = np.convolve(white, k, mode="same") * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * t))
    hum = 0.3 * np.sin(2 * np.pi * 50 * t)
    noise = babble + hum
    sig_p = np.mean(a[np.abs(a) > 0.01] ** 2) if np.any(np.abs(a) > 0.01) else 1e-4
    noise *= np.sqrt(sig_p / (10 ** (snr_db / 10)) / np.mean(noise ** 2))
    return np.clip(a + noise, -1, 1).astype(np.float32)


AUDIO = {
    "en": ("en-US", "Here is a space question. Which planet has the largest number of moons?"),
    "fr": ("fr-FR", "Question de géographie. Quelle est la capitale de l'Australie ?"),
}
AR_TEXT = "سؤال في الجغرافيا. ما هي عاصمة اليابان؟"


def make_audio():
    for lang, (culture, text) in AUDIO.items():
        raw = OUT / f"_raw_{lang}.wav"
        sapi(text, culture, raw)
        a = pad(read_any(raw))
        raw.unlink()
        write_wav(OUT / f"audio_{lang}.wav", a)
        write_wav(OUT / f"audio_{lang}_noisy.wav", add_noise(a, 10.0, seed=len(lang)))
    raw = OUT / "_raw_ar.mp3"
    asyncio.run(edge(AR_TEXT, "ar-SA-HamedNeural", raw))
    a = pad(read_any(raw))
    raw.unlink()
    write_wav(OUT / "audio_ar.wav", a)
    write_wav(OUT / "audio_ar_noisy.wav", add_noise(a, 10.0, seed=7))

    # paused question: speaker stops for 1.1 s mid-sentence (longer than the 0.7 s endpoint)
    p1, p2 = OUT / "_p1.wav", OUT / "_p2.wav"
    sapi("Which river is the longest", "en-US", p1)
    sapi("in Africa?", "en-US", p2)
    a = np.concatenate([pad(read_any(p1), 0.8, 0.0), np.zeros(int(1.1 * SR), np.float32), pad(read_any(p2), 0.0, 1.2)])
    p1.unlink(); p2.unlink()
    write_wav(OUT / "audio_en_paused.wav", a)

    # statement only (must NOT become a question)
    s = OUT / "_s.wav"
    sapi("Thanks everyone, we will continue after a short break.", "en-US", s)
    write_wav(OUT / "audio_en_statement.wav", pad(read_any(s)))
    s.unlink()

    # word problem: multi-sentence question with numbers that must be preserved
    s = OUT / "_wp.wav"
    sapi("A train leaves Paris at 3 PM travelling at 120 kilometres per hour. How far has it travelled by 5 PM?", "en-US", s)
    write_wav(OUT / "audio_en_multisentence.wav", pad(read_any(s)))
    s.unlink()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["images", "video", "audio"]
    if "images" in which:
        make_images()
    if "video" in which:
        make_video()
    if "audio" in which:
        make_audio()
    print("fixtures in", OUT)
