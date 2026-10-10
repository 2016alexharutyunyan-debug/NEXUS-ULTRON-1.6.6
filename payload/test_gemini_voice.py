from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path


def powershell_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    classic = os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return classic if os.path.exists(classic) else "powershell.exe"


def write_wave_file(filename: Path, pcm: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> None:
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def play_audio(path: Path) -> None:
    uri = path.resolve().as_uri().replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore
$player = [System.Windows.Media.MediaPlayer]::new()
$player.Open([Uri]'{uri}')
$player.Volume = 1
$player.Play()
$deadline = [DateTime]::Now.AddSeconds(30)
while (-not $player.NaturalDuration.HasTimeSpan -and [DateTime]::Now -lt $deadline) {{
    Start-Sleep -Milliseconds 100
}}
if ($player.NaturalDuration.HasTimeSpan) {{
    Start-Sleep -Milliseconds ([int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 350)
}} else {{
    Start-Sleep -Seconds 4
}}
$player.Stop()
$player.Close()
"""
    subprocess.run(
        [
            powershell_path(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=True,
        text=True,
    )


def find_audio_data(value):
    if isinstance(value, dict):
        output_audio = value.get("output_audio") or value.get("outputAudio")
        if isinstance(output_audio, dict) and isinstance(output_audio.get("data"), str):
            return output_audio["data"]
        inline_data = value.get("inlineData") or value.get("inline_data")
        if isinstance(inline_data, dict) and isinstance(inline_data.get("data"), str):
            return inline_data["data"]
        for item in value.values():
            found = find_audio_data(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_audio_data(item)
            if found:
                return found
    return None


def main() -> int:
    key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("JARVIS_AI_API_KEY", "").strip()
    )
    if not key:
        print("GEMINI_API_KEY is not set.")
        print("Run SET_GEMINI_KEY.bat, then run this test again.")
        return 1

    model = os.environ.get("JARVIS_GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
    voice = os.environ.get("JARVIS_GEMINI_TTS_VOICE", "Charon")
    prompt = (
        "Say clearly in English, in a calm, natural, futuristic AI assistant voice. "
        "Do not add extra words.\n\n"
        "Speak in a deep, controlled, metallic synthetic AI voice without imitating any real person. "
        "Transcript: Hello Alex. ULTRON is online and speaking in English-only mode."
    )
    fd, raw_path = tempfile.mkstemp(prefix="jarvis_gemini_voice_test_", suffix=".wav")
    os.close(fd)
    audio_path = Path(raw_path)

    try:
        print("Generating Gemini voice...")
        payload = {
            "model": model,
            "input": prompt,
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice}]},
        }
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        audio_data = find_audio_data(data)
        if not audio_data:
            print("Gemini did not return audio.")
            return 2

        write_wave_file(audio_path, base64.b64decode(audio_data))
        print("Playing Gemini voice test...")
        play_audio(audio_path)
        print("Done. If you heard ULTRON, Gemini voice is ready.")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"Gemini voice HTTP error: {exc.code} {exc.reason}")
        try:
            print(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            pass
        return 3
    except Exception as exc:
        print(f"Gemini voice test failed: {exc}")
        return 3
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
