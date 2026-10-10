from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


WAKE_PHRASES = (
    "welcome",
    "welcom",
    "wellcom",
    "wellcome",
    "well come",
    "welcome ultron",
    "welcom ultron",
    "wellcom ultron",
    "wellcome ultron",
    "well come ultron",
    "wake up ultron",
    "hello ultron",
    "hey ultron",
    "open ultron",
    "start ultron",
)


def project_root() -> Path:
    here = Path(__file__).resolve()
    for folder in (here.parent, *here.parents):
        if (folder / "payload" / "main.py").exists():
            return folder
        if (folder / "START_JARVIS.bat").exists():
            return folder
        if (folder / "payload" / "run_1_2_8_tts_fix.bat").exists():
            return folder
    return here.parent.parent


def start_jarvis() -> None:
    root = project_root()
    payload = root / "payload"
    main_py = payload / "main.py"
    if main_py.exists():
        venv_python = payload / ".venv" / "Scripts" / "python.exe"
        python_exe = str(venv_python) if venv_python.exists() else sys.executable
        subprocess.Popen(
            [python_exe, str(main_py)],
            cwd=str(payload),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return

    start_file = root / "START_JARVIS.bat"
    if start_file.exists():
        subprocess.Popen(
            [str(start_file)],
            cwd=str(root),
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return
    run_file = root / "payload" / "run_1_2_8_tts_fix.bat"
    if run_file.exists():
        subprocess.Popen(
            [str(run_file)],
            cwd=str(payload),
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return
    raise FileNotFoundError(f"Could not find NEXUS files near {Path(__file__).resolve()}")


def listen_once() -> tuple[str, float]:
    try:
        import sounddevice as sd
        import speech_recognition as sr
        import numpy as np
    except Exception as exc:
        raise RuntimeError(f"Voice packages missing: {exc}")

    try:
        device = sd.query_devices(kind="input")
        sample_rate = int(float(device.get("default_samplerate", 44100)))
        sample_rate = sample_rate if sample_rate >= 8000 else 44100
    except Exception:
        sample_rate = 44100

    recording = sd.rec(
        int(4.0 * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocking=True,
    )
    samples = np.asarray(recording, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return "", 0.0
    samples = samples - float(np.mean(samples))
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < 0.002:
        return "", peak
    gain = min(10.0, 0.85 / max(peak, 1e-6))
    samples = np.clip(samples * gain, -1.0, 1.0)
    pcm16 = (samples * 32767.0).astype(np.int16).tobytes()

    recognizer = sr.Recognizer()
    audio = sr.AudioData(pcm16, sample_rate, 2)
    try:
        return recognizer.recognize_google(audio, language="en-US").strip().lower(), peak
    except Exception:
        return "", peak


def is_wake_phrase(heard: str) -> bool:
    if any(phrase in heard for phrase in WAKE_PHRASES):
        return True
    words = set(heard.replace(",", " ").replace(".", " ").split())
    wake_words = {"welcome", "welcom", "wellcom", "wellcome", "open", "start", "wake", "hello", "hey"}
    ultron_words = {"ultron", "ultra", "altron"}
    if wake_words & words and ultron_words & words:
        return True
    short_wake_only = {"welcome", "welcom", "wellcom", "wellcome"}
    return bool(short_wake_only & words and len(words) <= 3)


def main() -> int:
    print("ULTRON Wake Launcher")
    print("Say: welcome")
    print("Or say: welcome Ultron")
    print("Leave this window open, or install it to Windows Startup.")
    print("")
    while True:
        try:
            print("Listening...", flush=True)
            heard, peak = listen_once()
            if heard:
                print(f"Heard: {heard}  | mic peak: {peak:.4f}", flush=True)
            else:
                print(f"No wake phrase. Mic peak: {peak:.4f}", flush=True)
            if is_wake_phrase(heard):
                print("Wake phrase detected. Opening ULTRON...")
                start_jarvis()
                time.sleep(8)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Wake launcher error: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
