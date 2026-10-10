from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def powershell_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    classic = os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return classic if os.path.exists(classic) else "powershell.exe"


def play_mp3(path: Path) -> None:
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


async def main() -> int:
    try:
        import edge_tts
    except Exception:
        print("edge-tts is not installed yet.")
        print("Run INSTALL_VOICE.bat, then run this test again.")
        return 1

    voice = os.environ.get("JARVIS_EDGE_VOICE", "en-US-GuyNeural")
    rate = os.environ.get("JARVIS_EDGE_RATE", "-6%")
    pitch = os.environ.get("JARVIS_EDGE_PITCH", "-20Hz")
    text = "Hello Alex. ULTRON is online. All NEXUS systems are operational."
    fd, raw_path = tempfile.mkstemp(prefix="jarvis_edge_voice_test_", suffix=".mp3")
    os.close(fd)
    audio_path = Path(raw_path)

    try:
        print("Generating ULTRON neural voice...")
        await edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch).save(str(audio_path))
        print("Playing voice test...")
        play_mp3(audio_path)
        print("Done. If you heard the deep voice, ULTRON voice is ready.")
        return 0
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
