"""Render the harder test set (tests/hard_cases.py) into images and speech (Windows SAPI en-US / fr-FR)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hard_cases import AUDIO_CASES, IMAGE_CASES  # noqa: E402
from make_fixtures import add_noise, font, pad, read_any, sapi, write_wav  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hard"


def render(case: dict) -> Image.Image:
    style = case["style"]
    dark = style == "dark"
    w = 1280
    size = 26 if dark else 34
    h = 160 + len(case["lines"]) * (size + 18) + len(case["options"]) * (size + 30) + 60
    bg, fg, card = ((24, 26, 33), (235, 235, 240), (38, 41, 52)) if dark else ((210, 220, 235), (25, 25, 35), (255, 255, 255))
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 40, w - 60, h - 40), 24, fill=card)
    y = 80
    for i, line in enumerate(case["lines"]):
        is_title = i == 0 and len(case["lines"]) > 1 and len(line) < 20
        d.text((110, y), line, font=font(size - 6 if is_title else size, bold=not is_title), fill=(200, 70, 70) if is_title else fg)
        y += size + 18
    y += 10
    for i, opt in enumerate(case["options"]):
        label = f"{i + 1}. {opt}" if style == "numbered" else f"{'ABCD'[i]}) {opt}"
        d.rounded_rectangle((110, y, 700, y + size + 20), 10, fill=(55, 60, 75) if dark else (234, 239, 250))
        d.text((128, y + 6), label, font=font(size - 2), fill=fg)
        y += size + 30
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for c in IMAGE_CASES:
        render(c).save(OUT / f"{c['id']}.png")
    for c in AUDIO_CASES:
        raw = OUT / f"_raw_{c['id']}.wav"
        sapi(c["text"], "en-US" if c["lang"] == "en" else "fr-FR", raw)
        a = pad(read_any(raw))
        raw.unlink()
        write_wav(OUT / f"{c['id']}.wav", a)
        write_wav(OUT / f"{c['id']}_noisy.wav", add_noise(a, 10.0, seed=len(c["id"])))
    print("hard fixtures in", OUT)


if __name__ == "__main__":
    main()
