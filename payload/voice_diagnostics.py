from __future__ import annotations

import math
import time


def main() -> int:
    print("JARVIS microphone diagnostics")
    print("=============================")
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        print(f"Missing voice package: {exc}")
        print("Run INSTALL_VOICE.bat, then try again.")
        return 1

    print("\nDefault devices:", sd.default.device)
    print("\nAvailable audio devices:")
    print(sd.query_devices())

    try:
        device = sd.query_devices(kind="input")
        sample_rate = int(float(device.get("default_samplerate", 44100)))
        sample_rate = sample_rate if sample_rate >= 8000 else 44100
    except Exception:
        sample_rate = 44100

    print("\nSpeak now. Recording microphone level for 3 seconds...")
    time.sleep(0.6)
    try:
        recording = sd.rec(
            int(3.0 * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocking=True,
        )
    except Exception as exc:
        print(f"Microphone could not start: {exc}")
        print("Open Windows microphone privacy/settings and allow desktop apps.")
        return 1

    samples = np.asarray(recording, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        print("Microphone returned no audio.")
        return 1

    samples = samples - float(np.mean(samples))
    peak = float(np.max(np.abs(samples)))
    rms = float(math.sqrt(float(np.mean(samples * samples))))
    print(f"\nPeak: {peak:.5f}")
    print(f"RMS:  {rms:.5f}")

    if peak < 0.002 or rms < 0.0004:
        print("\nResult: microphone is detected, but the signal is too quiet.")
        print("Try raising input volume, choosing another default microphone, or moving closer.")
        return 2

    print("\nResult: microphone signal looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
