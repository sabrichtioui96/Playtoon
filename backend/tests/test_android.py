"""Acceptance test 10: the processed result is displayed in the Android application.

Installs the debug APK on a running emulator/device, points it at the test server
(10.0.2.2 = host loopback from the emulator), feeds a question, then reads the live UI through
uiautomator and saves a screenshot as evidence."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from conftest import FIX, PORT, ROOT, record, wait_for

ADB = shutil.which("adb") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe")
APK = ROOT.parent / "android/app/build/outputs/apk/debug/app-debug.apk"
DOCS = ROOT.parent / "docs"


def adb(*args, check=True, binary=False):
    r = subprocess.run([ADB, *args], capture_output=True, check=False)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.decode(errors='replace')}")
    return r.stdout if binary else r.stdout.decode("utf-8", errors="replace")


def device_ready() -> bool:
    try:
        out = adb("devices")
    except (RuntimeError, FileNotFoundError):
        return False
    return any(l.endswith("\tdevice") for l in out.splitlines()[1:])


def ui_text() -> str:
    adb("shell", "uiautomator", "dump", "/sdcard/playtoon_ui.xml")
    xml = adb("exec-out", "cat", "/sdcard/playtoon_ui.xml")
    return " | ".join(t for t in re.findall(r'text="([^"]*)"', xml) if t)


def test_10_android_displays_result(client):
    if not device_ready():
        pytest.skip("no Android emulator/device attached (adb devices)")
    assert APK.exists(), f"build the app first: {APK}"
    adb("install", "-r", "-g", str(APK))           # -g grants runtime permissions for the test run
    adb("shell", "am", "force-stop", "com.playtoon.app")
    adb("shell", "am", "start", "-n", "com.playtoon.app/.MainActivity", "--es", "server_url", f"http://10.0.2.2:{PORT}")
    assert wait_for(lambda: client.get("/stats").json()["clients"] >= 1, 60), "app never connected to the engine"

    client.post("/ingest/image", files={"file": ("image_question.png", (FIX / "image_question.png").read_bytes(), "image/png")})
    q = wait_for(lambda: next((x for x in client.get("/questions").json() if x["status"] == "answered"), None), 60)
    assert q

    def shown():
        t = ui_text()
        return t if ("Which planet has the largest number of moons?" in t and "Suggested answer: Saturn" in t) else None
    text = wait_for(shown, 30, 1)
    assert text, ui_text()
    for needle in ["Source: visual", "Language: English", "A) Jupiter", "B) Saturn  ✓", "Confidence:", "Processing:", "Connected"]:
        assert needle in text, (needle, text)

    DOCS.mkdir(exist_ok=True)
    (DOCS / "android_test10.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    record("test_10_android_displays_result", ui_text=text, screenshot="docs/android_test10.png",
           device=adb("shell", "getprop", "ro.product.model").strip(),
           sdk=adb("shell", "getprop", "ro.build.version.sdk").strip())
