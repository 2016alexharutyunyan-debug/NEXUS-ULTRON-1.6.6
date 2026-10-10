from __future__ import annotations

import json
import os
import urllib.parse
import urllib.error
import urllib.request


ENDPOINT = (
    os.environ.get("JARVIS_AI_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta")
    .strip()
    .rstrip("/")
)
MODEL = os.environ.get("JARVIS_AI_MODEL", "gemini-3.5-flash-lite").strip()


def normalize_gemini_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    for suffix in ("/openai/chat/completions", "/chat/completions", "/openai"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)].rstrip("/")
    if endpoint.endswith("/v1") or endpoint.endswith("/v1beta"):
        return endpoint
    return "https://generativelanguage.googleapis.com/v1beta"


def main() -> int:
    key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("JARVIS_AI_API_KEY", "").strip()
    )
    if not key:
        print("GEMINI_API_KEY is not set.")
        print("Run SET_GEMINI_KEY.bat, then close and reopen this terminal.")
        return 1

    payload = {
        "systemInstruction": {"parts": [{"text": "You are ULTRON. Reply briefly in English."}]},
        "contents": [{"role": "user", "parts": [{"text": "Say: Gemini test OK"}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 64},
    }
    request = urllib.request.Request(
        f"{normalize_gemini_endpoint(ENDPOINT)}/models/{urllib.parse.quote(MODEL, safe='')}:generateContent?key={urllib.parse.quote(key)}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        print("Gemini test OK:")
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        print("".join(part.get("text", "") for part in parts).strip())
        return 0
    except urllib.error.HTTPError as exc:
        print(f"Gemini HTTP error: {exc.code} {exc.reason}")
        try:
            print(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            pass
        return 2
    except Exception as exc:
        print(f"Gemini test failed: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
