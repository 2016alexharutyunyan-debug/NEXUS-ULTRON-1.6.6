from __future__ import annotations

import ast
import base64
import concurrent.futures
import ctypes
import hmac
import json
import math
import os
import queue
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import zipfile
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import mediapipe as mp
import numpy as np
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QThread, Signal, QUrl, QObject, QEvent,
    QEasingCurve, QPropertyAnimation
)
from PySide6.QtGui import (
    QAction, QColor, QImage, QPainter, QPen, QBrush, QPixmap,
    QTransform, QDesktopServices, QGuiApplication, QFont, QIcon
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QTextEdit, QLineEdit,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QCalendarWidget, QLCDNumber, QSlider,
    QCheckBox, QSpinBox, QTabWidget, QProgressBar, QGraphicsDropShadowEffect,
    QMenu, QInputDialog, QAbstractItemView, QStackedWidget, QSystemTrayIcon, QDialog
)

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from gesture_engine import (
    DEFAULT_ASPECT, FingerTapDetector, PalmSwipeDetector, TIP as FINGER_TIP, map_camera_to_rect,
)
from gesture_overlay import KeyboardOverlay, ToastOverlay

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_AVAILABLE = True
except Exception:
    QMediaPlayer = None
    QAudioOutput = None
    QVideoWidget = None
    MULTIMEDIA_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    PSUTIL_AVAILABLE = False

IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
        WIN32_AVAILABLE = True
    except Exception:
        win32api = win32con = win32gui = win32process = None
        WIN32_AVAILABLE = False
else:
    win32api = win32con = win32gui = win32process = None
    WIN32_AVAILABLE = False


APP_NAME = "NEXUS ULTRON"
APP_VERSION = "1.6.6-reliable-typing-and-palm-backspace"
DEFAULT_AI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AI_MODEL = "gemini-3.1-flash-lite"
AI_TIMEOUT_SECONDS = int(os.environ.get("JARVIS_AI_TIMEOUT_SECONDS", "7"))
AI_MAX_OUTPUT_TOKENS = int(os.environ.get("JARVIS_AI_MAX_OUTPUT_TOKENS", "72"))
VOICE_RECORD_SECONDS = float(os.environ.get("JARVIS_VOICE_RECORD_SECONDS", "5.0"))
GEMINI_TTS_TIMEOUT_SECONDS = int(os.environ.get("JARVIS_GEMINI_TTS_TIMEOUT_SECONDS", "5"))
EDGE_TTS_TIMEOUT_SECONDS = int(os.environ.get("JARVIS_EDGE_TTS_TIMEOUT_SECONDS", "10"))
VOICE_PRIORITY = os.environ.get("JARVIS_VOICE_PRIORITY", "fast").strip().lower()
DEFAULT_JARVIS_PROMPT = (
    "You are ULTRON, the fast and precise English voice assistant inside NEXUS. "
    "Speak with controlled confidence: concise, intelligent, calm, and slightly imposing. "
    "Reply only in English, even if the user uses another language. "
    "Answer immediately and keep answers short unless the user asks for detail. Usually use 1 short sentence. "
    "Do not use markdown, bullet points, code blocks, emojis, or technical formatting. "
    "For desktop commands, confirm briefly and naturally. Never claim to be JARVIS."
)


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def app_data_dir() -> Path:
    if IS_WINDOWS:
        root = Path(os.getenv("APPDATA", Path.home()))
    else:
        root = Path.home() / ".config"
    path = root / "HoloDeskAI"
    path.mkdir(parents=True, exist_ok=True)
    return path


HAND_MODEL_PATH = resource_path("models", "hand_landmarker.task")
FACE_MODEL_PATH = resource_path("models", "face_landmarker.task")
SETTINGS_PATH = app_data_dir() / "settings.json"
AIR_LOG_PATH = app_data_dir() / "air_typing.log"
SUPABASE_PROJECT_URL = "https://dashbmuvqbzmhvnbemcu.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_TLLyvBd4Xh1t714kMBSk3Q_47BzsLtC"


def air_log(message: str) -> None:
    """Small diagnostic log for air typing / palm backspace (%APPDATA%\\HoloDeskAI\\air_typing.log)."""
    try:
        if AIR_LOG_PATH.exists() and AIR_LOG_PATH.stat().st_size > 400_000:
            AIR_LOG_PATH.write_text("", encoding="utf-8")
        with AIR_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%H:%M:%S ") + message + "\n")
    except Exception:
        pass
WORKSPACE_PATH = app_data_dir() / "workspace.json"
WORLD_MAP_PATH = app_data_dir() / "world_map.json"
SELF_EDIT_PATH = app_data_dir() / "self_edit.json"
PROJECTS_PATH = Path.home() / "Documents" / "NEXUS Projects"


def safe_project_name(value: str, default: str = "jarvis_project") -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_ " else " " for char in value)
    cleaned = "_".join(cleaned.split()).strip("._-")
    return (cleaned or default)[:64]


def safe_relative_path(value: str) -> Path:
    raw = value.strip().replace("\\", "/")
    if not raw or "\x00" in raw or ":" in raw:
        raise ValueError("Invalid file path in the generated plan.")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe file path rejected: {value}")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        raise ValueError("The generated plan contains an empty file path.")
    return Path(*parts)


def json_object_from_text(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini did not return a project plan.")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("The project plan is not a JSON object.")
    return data


def normalize_project_plan(data: dict[str, Any], request: str) -> dict[str, Any]:
    project_name = safe_project_name(str(data.get("project_name", "jarvis_project")))
    summary = str(data.get("summary", request)).strip()[:1000]
    raw_files = data.get("files", [])
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("The project plan does not contain files.")
    if len(raw_files) > 18:
        raise ValueError("The project plan contains too many files. Maximum: 18.")

    files: list[dict[str, str]] = []
    total_size = 0
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError("A project file entry is invalid.")
        relative = safe_relative_path(str(item.get("path", "")))
        key = relative.as_posix().lower()
        if key in seen:
            raise ValueError(f"Duplicate file path: {relative.as_posix()}")
        seen.add(key)
        content = str(item.get("content", ""))
        total_size += len(content.encode("utf-8"))
        if total_size > 700_000:
            raise ValueError("The generated project is too large. Maximum: 700 KB.")
        files.append({"path": relative.as_posix(), "content": content})

    run_file = str(data.get("run_file", "")).strip()
    if run_file:
        run_file = safe_relative_path(run_file).as_posix()
    return {
        "project_name": project_name,
        "summary": summary,
        "files": files,
        "run_file": run_file,
        "request": request.strip(),
    }


def local_starter_plan(request: str) -> dict[str, Any]:
    low = request.lower()
    name_words = [word for word in request.split() if word.isalnum()][:5]
    name = safe_project_name(" ".join(name_words), "jarvis_project")
    if any(word in low for word in ("website", "web site", "html", "landing page")):
        data = {
            "project_name": name,
            "summary": "A local starter website generated by ULTRON.",
            "run_file": "index.html",
            "files": [
                {"path": "index.html", "content": "<!doctype html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\">\n  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n  <title>ULTRON Project</title>\n  <link rel=\"stylesheet\" href=\"styles.css\">\n</head>\n<body>\n  <main>\n    <h1>ULTRON Project</h1>\n    <p id=\"brief\"></p>\n    <button id=\"action\">Activate</button>\n  </main>\n  <script src=\"app.js\"></script>\n</body>\n</html>\n"},
                {"path": "styles.css", "content": "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#071018;color:#dffaff;font-family:Segoe UI,sans-serif}main{width:min(680px,calc(100% - 40px));border:1px solid #36b9db;padding:32px}button{padding:10px 18px;background:#123e52;color:#eaffff;border:1px solid #58cdea}h1{letter-spacing:0}\n"},
                {"path": "app.js", "content": f"document.querySelector('#brief').textContent = {json.dumps(request)};\ndocument.querySelector('#action').addEventListener('click',()=>alert('Project activated.'));\n"},
                {"path": "README.md", "content": f"# {name}\n\nGenerated by ULTRON Mission Builder.\n\n## Request\n\n{request}\n\nOpen `index.html` to run it.\n"},
            ],
        }
    else:
        data = {
            "project_name": name,
            "summary": "A local Python starter generated by ULTRON.",
            "run_file": "run.bat",
            "files": [
                {"path": "main.py", "content": f"from __future__ import annotations\n\nPROJECT_BRIEF = {request!r}\n\n\ndef main() -> None:\n    print('ULTRON project ready.')\n    print(PROJECT_BRIEF)\n\n\nif __name__ == '__main__':\n    main()\n"},
                {"path": "run.bat", "content": "@echo off\ncd /d \"%~dp0\"\npython main.py\npause\n"},
                {"path": "README.md", "content": f"# {name}\n\nGenerated by ULTRON Mission Builder.\n\n## Request\n\n{request}\n\nRun `run.bat`.\n"},
            ],
        }
    return normalize_project_plan(data, request)


def load_self_edit_config() -> dict[str, Any]:
    defaults = {
        "center_text": "ULTRON",
        "voice_style": "simple",
        "custom_prompt": "",
        "aliases": "mission => future self\npackage project => zip builder\nmy map => world map",
    }
    if not SELF_EDIT_PATH.exists():
        return defaults
    try:
        data = json.loads(SELF_EDIT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update({key: str(value) for key, value in data.items() if key in defaults})
            if defaults["center_text"].strip().upper() == "JARVIS":
                defaults["center_text"] = "ULTRON"
    except Exception:
        pass
    return defaults


def current_jarvis_prompt() -> str:
    config = load_self_edit_config()
    prompt = config.get("custom_prompt", "").strip()
    if prompt:
        return prompt + " Your assistant identity is ULTRON. Never call yourself JARVIS. Reply only in English."
    style = config.get("voice_style", "simple").strip().lower()
    if style == "cool":
        return DEFAULT_JARVIS_PROMPT + " Sound calm, confident, and slightly futuristic, but never dramatic."
    if style == "teacher":
        return DEFAULT_JARVIS_PROMPT + " Explain like a helpful teacher, with simple examples when useful."
    if style == "fast":
        return DEFAULT_JARVIS_PROMPT + " Be extra brief. Prefer one short sentence."
    return DEFAULT_JARVIS_PROMPT


def is_armenian_text(text: str) -> bool:
    return False


def choose_language(text: str) -> str:
    return "en"


def localized(en: str, hy: str, source: str) -> str:
    return en


def project_generation_intent(text: str) -> bool:
    normalized = "".join(char if char.isalnum() else " " for char in text.lower())
    words = set(normalized.split())
    action = bool(words & {"generate", "create", "build", "make", "design", "develop"})
    project = bool(words & {"app", "application", "program", "project", "software"})
    speech_misheard_app = bool(words & {"random", "randam", "randomly"}) and bool(words & {"map", "up"})
    return action and (project or speech_misheard_app)


def random_app_intent(text: str) -> bool:
    normalized = "".join(char if char.isalnum() else " " for char in text.lower())
    words = set(normalized.split())
    return project_generation_intent(text) and bool(words & {"random", "randam", "randomly"})


def contains_phrase(text: str, *phrases: str) -> bool:
    """True when any phrase occurs as whole words (so 'phone' does not match 'microphone')."""
    for phrase in phrases:
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text):
            return True
    return False


def dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def button_style() -> str:
    return """
        QPushButton {
            color: #EAFBFF;
            background: rgba(42, 91, 115, 190);
            border: 1px solid rgba(100, 230, 255, 80);
            border-radius: 9px;
            padding: 7px 10px;
        }
        QPushButton:hover { background: rgba(76, 143, 170, 225); }
        QPushButton:pressed { background: rgba(32, 74, 94, 240); }
        QPushButton:disabled { color: #6F8790; background: rgba(20, 35, 45, 160); }
    """


def input_style() -> str:
    return """
        QLineEdit, QTextEdit, QComboBox, QSpinBox {
            color: #EAFBFF;
            background: rgba(7, 13, 22, 220);
            border: 1px solid rgba(100, 220, 250, 90);
            border-radius: 8px;
            padding: 7px;
            selection-background-color: #28708A;
        }
    """


@dataclass
class AppSettings:
    show_camera: bool = True
    performance_mode: bool = False
    eye_tracking: bool = False
    eye_cursor: bool = False
    global_hand_control: bool = True
    phone_port: int = 8765
    ai_endpoint: str = ""
    ai_model: str = ""
    ai_key: str = ""
    tap_sensitivity: float = 1.0      # air-typing: 0.5 (strict) .. 4.0 (very sensitive)
    palm_swipe_dwell: float = 0.10    # palm must pause this long before the swipe-up (0 = off)
    kb_map_x0: float = 0.06           # part of the camera view that represents the keyboard
    kb_map_x1: float = 0.94
    kb_map_y0: float = 0.18
    kb_map_y1: float = 0.80

    @classmethod
    def load(cls) -> "AppSettings":
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            allowed = {k: data[k] for k in cls.__annotations__ if k in data}
            if allowed.get("ai_model") == "gemini-3.5-flash-lite":
                allowed["ai_model"] = DEFAULT_AI_MODEL
            return cls(**allowed)
        except Exception:
            return cls()

    def save(self) -> None:
        SETTINGS_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


class ExponentialSmoother:
    def __init__(self, alpha: float = 0.42, deadzone: float = 0.0025):
        self.alpha = alpha
        self.deadzone = deadzone
        self.value: Optional[tuple[float, float]] = None

    def update(self, point: tuple[float, float]) -> tuple[float, float]:
        if self.value is None:
            self.value = point
            return point
        dx = point[0] - self.value[0]
        dy = point[1] - self.value[1]
        if abs(dx) < self.deadzone:
            dx = 0.0
        if abs(dy) < self.deadzone:
            dy = 0.0
        speed = math.hypot(dx, dy)
        adaptive_alpha = clamp(self.alpha + speed * 2.4, self.alpha, 0.82)
        self.value = (
            self.value[0] + dx * adaptive_alpha,
            self.value[1] + dy * adaptive_alpha,
        )
        return self.value


class OneEuroPointFilter:
    """Low-latency adaptive filter for a normalized 2D hand point."""

    def __init__(self, min_cutoff: float = 1.15, beta: float = 0.08, derivative_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.derivative_cutoff = derivative_cutoff
        self.previous_raw: Optional[tuple[float, float]] = None
        self.previous_filtered: Optional[tuple[float, float]] = None
        self.previous_derivative = (0.0, 0.0)
        self.previous_time: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(0.001, cutoff))
        return 1.0 / (1.0 + tau / max(0.001, dt))

    def reset(self) -> None:
        self.previous_raw = None
        self.previous_filtered = None
        self.previous_derivative = (0.0, 0.0)
        self.previous_time = None

    def update(self, point: tuple[float, float], timestamp: Optional[float] = None) -> tuple[float, float]:
        now = time.monotonic() if timestamp is None else timestamp
        if self.previous_raw is None or self.previous_filtered is None or self.previous_time is None:
            self.previous_raw = point
            self.previous_filtered = point
            self.previous_time = now
            return point

        dt = clamp(now - self.previous_time, 1.0 / 120.0, 0.2)
        raw_derivative = (
            (point[0] - self.previous_raw[0]) / dt,
            (point[1] - self.previous_raw[1]) / dt,
        )
        derivative_alpha = self._alpha(self.derivative_cutoff, dt)
        derivative = (
            self.previous_derivative[0] + derivative_alpha * (raw_derivative[0] - self.previous_derivative[0]),
            self.previous_derivative[1] + derivative_alpha * (raw_derivative[1] - self.previous_derivative[1]),
        )
        speed = math.hypot(*derivative)
        alpha = self._alpha(self.min_cutoff + self.beta * speed, dt)
        filtered = (
            self.previous_filtered[0] + alpha * (point[0] - self.previous_filtered[0]),
            self.previous_filtered[1] + alpha * (point[1] - self.previous_filtered[1]),
        )
        self.previous_raw = point
        self.previous_filtered = filtered
        self.previous_derivative = derivative
        self.previous_time = now
        return filtered


class StableRelativeCursor:
    """Confidence averaging, outlier rejection and adaptive relative motion."""

    def __init__(self, history_size: int = 6, deadzone: float = 0.0018):
        self.history: deque[tuple[float, float, float]] = deque(maxlen=history_size)
        self.filter = OneEuroPointFilter()
        self.previous: Optional[tuple[float, float]] = None
        self.deadzone = deadzone
        self.missing_frames = 0

    def reset(self) -> None:
        self.history.clear()
        self.filter.reset()
        self.previous = None
        self.missing_frames = 0

    def mark_missing(self) -> bool:
        self.missing_frames += 1
        if self.missing_frames < 6:
            return False
        self.reset()
        return True

    def update(
        self,
        point: tuple[float, float],
        confidence: float,
        timestamp: Optional[float] = None,
    ) -> Optional[tuple[float, float]]:
        if confidence < 0.45:
            self.mark_missing()
            return None
        self.missing_frames = 0

        if self.history:
            center_x = sum(sample[0] for sample in self.history) / len(self.history)
            center_y = sum(sample[1] for sample in self.history) / len(self.history)
            if math.hypot(point[0] - center_x, point[1] - center_y) > 0.22:
                return None

        self.history.append((point[0], point[1], confidence))
        total_weight = 0.0
        average_x = 0.0
        average_y = 0.0
        for age, sample in enumerate(self.history, start=1):
            weight = max(0.1, sample[2]) * age
            average_x += sample[0] * weight
            average_y += sample[1] * weight
            total_weight += weight
        averaged = (average_x / total_weight, average_y / total_weight)
        filtered = self.filter.update(averaged, timestamp)
        if self.previous is None:
            self.previous = filtered
            return (0.0, 0.0)

        dx = filtered[0] - self.previous[0]
        dy = filtered[1] - self.previous[1]
        self.previous = filtered
        if abs(dx) < self.deadzone:
            dx = 0.0
        if abs(dy) < self.deadzone:
            dy = 0.0
        speed = math.hypot(dx, dy)
        if speed == 0.0:
            return (0.0, 0.0)
        gain = clamp(0.78 + speed * 58.0, 0.78, 4.2)
        return (dx * gain, dy * gain)


class PinchHysteresis:
    def __init__(self, start_threshold: float = 0.082, release_threshold: float = 0.115):
        self.start_threshold = start_threshold
        self.release_threshold = release_threshold
        self.active = False

    def update(self, distance: float) -> bool:
        if self.active:
            self.active = distance < self.release_threshold
        else:
            self.active = distance < self.start_threshold
        return self.active


class HandTracker:
    """Phase 2: two-hand MediaPipe tracking with smoothing, jitter filtering and pinch hysteresis."""

    def __init__(self, model_path: Path):
        if not model_path.exists():
            raise FileNotFoundError(f"Hand model not found: {model_path}")
        base_options = python.BaseOptions(model_asset_path=str(model_path))
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.55,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        self.timestamp_ms = 0
        self.smoothers = [ExponentialSmoother(), ExponentialSmoother()]
        self.pinch_filters = [PinchHysteresis(), PinchHysteresis()]

    @staticmethod
    def _iso_dist(points: list[tuple[float, float, float]], i: int, j: int, aspect: float) -> float:
        return math.hypot((points[i][0] - points[j][0]) * aspect, points[i][1] - points[j][1])

    @classmethod
    def _finger_map(cls, points: list[tuple[float, float, float]], aspect: float = DEFAULT_ASPECT) -> dict[str, bool]:
        """A finger counts as extended when its tip is clearly farther from the wrist than its PIP joint.
        Unlike the old 'tip above PIP' test this works for any hand rotation."""
        d = lambda i, j: cls._iso_dist(points, i, j, aspect)
        return {
            "thumb": d(4, 0) > d(3, 0) * 1.03,
            "index": d(8, 0) > d(6, 0) * 1.10,
            "middle": d(12, 0) > d(10, 0) * 1.10,
            "ring": d(16, 0) > d(14, 0) * 1.10,
            "pinky": d(20, 0) > d(18, 0) * 1.10,
        }

    @classmethod
    def _palm_open(cls, points: list[tuple[float, float, float]], fingers: dict[str, bool], aspect: float = DEFAULT_ASPECT) -> bool:
        """Open palm = at least 4 fingers extended and the hand is not a narrow 'spike'.
        Spread is measured relative to palm width, so a distant or relaxed hand still counts."""
        palm_width = max(1e-4, cls._iso_dist(points, 5, 17, aspect))
        spread = cls._iso_dist(points, 8, 20, aspect) / palm_width
        return sum(fingers.values()) >= 4 and spread >= 0.80

    @staticmethod
    def _gesture(fingers: dict[str, bool], pinch: bool, palm_open: bool) -> str:
        extended = sum(fingers.values())
        if pinch:
            return "pinch"
        if palm_open:
            return "open"
        if extended <= 1 and fingers.get("index"):
            return "point"
        if extended == 0:
            return "fist"
        if fingers.get("index") and fingers.get("middle") and extended == 2:
            return "victory"
        return "hand"

    def process(self, bgr_frame: np.ndarray, aspect: float = DEFAULT_ASPECT) -> list[dict[str, Any]]:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self.timestamp_ms += 33
        result = self.landmarker.detect_for_video(mp_image, self.timestamp_ms)
        stamp = time.monotonic()

        raw_hands: list[dict[str, Any]] = []
        for index, landmarks in enumerate(result.hand_landmarks):
            points = [(lm.x, lm.y, lm.z) for lm in landmarks]
            handedness = "Unknown"
            confidence = 0.0
            if index < len(result.handedness) and result.handedness[index]:
                handedness = result.handedness[index][0].category_name or "Unknown"
                confidence = float(result.handedness[index][0].score or 0.0)
            raw_hands.append({"points": points, "handedness": handedness, "confidence": confidence})

        raw_hands.sort(key=lambda item: item["points"][0][0])
        hands: list[dict[str, Any]] = []
        for slot, item in enumerate(raw_hands[:2]):
            points = item["points"]
            fingers = self._finger_map(points, aspect)
            pinch_distance = dist(points[4], points[8])
            palm_width = max(0.001, dist(points[5], points[17]))
            pinch_ratio = pinch_distance / palm_width
            pinching = self.pinch_filters[slot].update(pinch_distance)
            palm_open = self._palm_open(points, fingers, aspect)
            sx, sy = self.smoothers[slot].update((points[8][0], points[8][1]))
            gesture = self._gesture(fingers, pinching, palm_open)
            hands.append({
                "points": points,
                "handedness": item["handedness"],
                "confidence": item["confidence"],
                "index": (sx, sy, points[8][2]),
                "thumb": points[4],
                "palm": points[9],
                "fingers": fingers,
                "pinch_distance": pinch_distance,
                "pinch_ratio": pinch_ratio,
                "pinch_strength": clamp(1.0 - pinch_distance / 0.10, 0.0, 1.0),
                "pinching": pinching,
                "palm_open": palm_open,
                "gesture": gesture,
                "aspect": aspect,
                "t": stamp,
            })
        return hands

    def close(self) -> None:
        self.landmarker.close()


class FaceTracker:
    """Phase 8: optional MediaPipe iris/head tracking."""

    def __init__(self, model_path: Path):
        if not model_path.exists():
            raise FileNotFoundError(f"Face model not found: {model_path}")
        base_options = python.BaseOptions(model_asset_path=str(model_path))
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)
        self.timestamp_ms = 0
        self.gaze_smoother = ExponentialSmoother(alpha=0.22, deadzone=0.0015)

    @staticmethod
    def _mean(points: list[Any], ids: list[int]) -> tuple[float, float]:
        valid = [points[i] for i in ids if i < len(points)]
        if not valid:
            return 0.5, 0.5
        return sum(p.x for p in valid) / len(valid), sum(p.y for p in valid) / len(valid)

    def process(self, bgr_frame: np.ndarray) -> Optional[dict[str, Any]]:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self.timestamp_ms += 33
        result = self.landmarker.detect_for_video(mp_image, self.timestamp_ms)
        if not result.face_landmarks:
            return None
        points = result.face_landmarks[0]
        nose = points[1]
        left_iris = self._mean(points, [474, 475, 476, 477])
        right_iris = self._mean(points, [469, 470, 471, 472])
        iris = ((left_iris[0] + right_iris[0]) / 2, (left_iris[1] + right_iris[1]) / 2)

        # Face-relative gaze estimate. It is intentionally conservative to reduce drift.
        left_corner = self._mean(points, [33, 133])
        right_corner = self._mean(points, [362, 263])
        eye_center = ((left_corner[0] + right_corner[0]) / 2, (left_corner[1] + right_corner[1]) / 2)
        gaze_x = clamp(0.5 + (iris[0] - eye_center[0]) * 8.0 + (nose.x - 0.5) * 0.75, 0.0, 1.0)
        gaze_y = clamp(0.5 + (iris[1] - eye_center[1]) * 11.0 + (nose.y - 0.5) * 0.45, 0.0, 1.0)
        gaze_x, gaze_y = self.gaze_smoother.update((gaze_x, gaze_y))
        return {
            "gaze": (gaze_x, gaze_y),
            "head": (nose.x - 0.5, nose.y - 0.5),
            "nose": (nose.x, nose.y),
        }

    def close(self) -> None:
        self.landmarker.close()


class CameraWorker(threading.Thread):
    """Continuously captures only the newest webcam frame outside the Qt UI thread."""

    def __init__(self, camera_index: int = 0, width: int = 640, height: int = 360, target_fps: int = 30):
        super().__init__(name="HoloDeskCamera", daemon=True)
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._sequence = 0
        self._fps = 0.0
        self._opened = False
        self._status = "Starting camera…"
        self._cap: Optional[cv2.VideoCapture] = None

    def run(self) -> None:
        backend = cv2.CAP_DSHOW if IS_WINDOWS else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.camera_index, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.camera_index)
        self._cap = cap
        if not cap.isOpened():
            with self._lock:
                self._status = "Camera not found"
            return

        # MJPG + one-frame buffer prevents an old-frame queue from building up.
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        with self._lock:
            self._opened = True
            self._status = "Camera active"

        frames = 0
        started = time.perf_counter()
        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    with self._lock:
                        self._status = "Camera frame unavailable"
                    time.sleep(0.01)
                    continue

                frame = cv2.flip(frame, 1)
                frames += 1
                now = time.perf_counter()
                elapsed = now - started
                with self._lock:
                    self._latest_frame = frame
                    self._sequence += 1
                    self._status = "Camera active"
                    if elapsed >= 1.0:
                        self._fps = frames / elapsed
                        frames = 0
                        started = now
        finally:
            cap.release()
            with self._lock:
                self._opened = False
                if self._status == "Camera active":
                    self._status = "Camera stopped"

    def snapshot(self) -> tuple[Optional[np.ndarray], int, float, str, bool]:
        with self._lock:
            return self._latest_frame, self._sequence, self._fps, self._status, self._opened

    def stop(self) -> None:
        self._stop_event.set()


class TrackingWorker(threading.Thread):
    """Runs MediaPipe at its own cadence and publishes the newest result only."""

    def __init__(
        self,
        camera: CameraWorker,
        performance_mode: Callable[[], bool],
        eye_tracking_enabled: Callable[[], bool],
        boost: Optional[Callable[[], bool]] = None,
    ):
        super().__init__(name="HoloDeskTracking", daemon=True)
        self.camera = camera
        self.boost = boost
        self.performance_mode = performance_mode
        self.eye_tracking_enabled = eye_tracking_enabled
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._hands: list[dict[str, Any]] = []
        self._face: Optional[dict[str, Any]] = None
        self._sequence = 0
        self._fps = 0.0
        self._status = "Starting hand tracker…"
        self._hand_tracker: Optional[HandTracker] = None
        self._face_tracker: Optional[FaceTracker] = None
        self._eye_model_failed = False

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    def run(self) -> None:
        try:
            self._hand_tracker = HandTracker(HAND_MODEL_PATH)
        except Exception as exc:
            self._set_status(f"Hand model: {exc}")
            return

        last_camera_sequence = -1
        next_process_at = 0.0
        processed = 0
        fps_started = time.perf_counter()
        eye_cycle = 0
        self._set_status("Hand tracking active")

        try:
            while not self._stop_event.is_set():
                performance = bool(self.performance_mode())
                boosted = bool(self.boost()) if self.boost is not None else False
                interval = 1.0 / (30.0 if boosted else (15.0 if performance else 20.0))
                now = time.perf_counter()
                if now < next_process_at:
                    time.sleep(min(0.004, next_process_at - now))
                    continue

                frame, camera_sequence, _, camera_status, opened = self.camera.snapshot()
                if frame is None or camera_sequence == last_camera_sequence:
                    if not opened and camera_status == "Camera not found":
                        self._set_status(camera_status)
                    time.sleep(0.005)
                    continue

                last_camera_sequence = camera_sequence
                next_process_at = now + interval
                target_size = (384, 216) if performance else (512, 288)
                tracking_frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)

                try:
                    aspect = frame.shape[1] / max(1, frame.shape[0])
                    hands = self._hand_tracker.process(tracking_frame, aspect)
                except Exception as exc:
                    self._set_status(f"Tracking error: {exc}")
                    time.sleep(0.05)
                    continue

                face: Optional[dict[str, Any]] = None
                face_processed = False
                eye_enabled = bool(self.eye_tracking_enabled())
                if eye_enabled:
                    if self._face_tracker is None and not self._eye_model_failed:
                        try:
                            self._face_tracker = FaceTracker(FACE_MODEL_PATH)
                        except Exception as exc:
                            self._eye_model_failed = True
                            self._set_status(f"Eye model: {exc}")
                    eye_cycle += 1
                    # Face/iris inference is heavier, so run it at half the hand cadence.
                    if self._face_tracker is not None and eye_cycle % 2 == 0:
                        face_processed = True
                        try:
                            face = self._face_tracker.process(tracking_frame)
                        except Exception:
                            face = None
                else:
                    self._eye_model_failed = False
                    if self._face_tracker is not None:
                        try:
                            self._face_tracker.close()
                        except Exception:
                            pass
                        self._face_tracker = None

                processed += 1
                elapsed = time.perf_counter() - fps_started
                with self._lock:
                    self._hands = hands
                    if face_processed or not eye_enabled:
                        self._face = face
                    self._sequence += 1
                    if not eye_enabled or not self._eye_model_failed:
                        self._status = "Hand tracking active"
                    if elapsed >= 1.0:
                        self._fps = processed / elapsed
                        processed = 0
                        fps_started = time.perf_counter()
        finally:
            if self._hand_tracker is not None:
                try:
                    self._hand_tracker.close()
                except Exception:
                    pass
            if self._face_tracker is not None:
                try:
                    self._face_tracker.close()
                except Exception:
                    pass

    def snapshot(self) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]], int, float, str]:
        with self._lock:
            return self._hands, self._face, self._sequence, self._fps, self._status

    def stop(self) -> None:
        self._stop_event.set()


class WindowsController:
    """Phase 1: enumerate and control real Windows application windows."""

    def __init__(self):
        self.available = bool(IS_WINDOWS and WIN32_AVAILABLE)
        self.cursor_lock = threading.Lock()   # key-press clicks and hand-driven cursor moves never interleave

    def press_backspace(self) -> bool:
        """One real Backspace key press (with scan code) for the focused application."""
        if not IS_WINDOWS:
            return False
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(0x08, 0x0E, 0, 0)
            time.sleep(0.01)
            user32.keybd_event(0x08, 0x0E, 2, 0)
            return True
        except Exception:
            return False

    def list_windows(self) -> list[dict[str, Any]]:
        if not self.available:
            return []
        rows: list[dict[str, Any]] = []

        def callback(hwnd: int, _: Any) -> None:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd).strip()
                if not title:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = ""
                if PSUTIL_AVAILABLE:
                    try:
                        process_name = psutil.Process(pid).name()
                    except Exception:
                        process_name = ""
                rect = win32gui.GetWindowRect(hwnd)
                rows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "pid": pid,
                    "process": process_name,
                    "rect": rect,
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "maximized": bool(win32gui.IsZoomed(hwnd)),
                })
            except Exception:
                return

        win32gui.EnumWindows(callback, None)
        rows.sort(key=lambda row: row["title"].lower())
        return rows

    def _valid(self, hwnd: int) -> bool:
        return bool(self.available and hwnd and win32gui.IsWindow(hwnd))

    def bring_to_front(self, hwnd: int) -> bool:
        if not self._valid(hwnd):
            return False
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                # Windows foreground-lock workaround.
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                win32gui.SetForegroundWindow(hwnd)
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            return True
        except Exception:
            return False

    def action(self, hwnd: int, action: str) -> bool:
        if not self._valid(hwnd):
            return False
        try:
            actions = {
                "minimize": win32con.SW_MINIMIZE,
                "maximize": win32con.SW_MAXIMIZE,
                "restore": win32con.SW_RESTORE,
            }
            if action in actions:
                win32gui.ShowWindow(hwnd, actions[action])
            elif action == "close":
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            elif action in {"snap_left", "snap_right"}:
                screen_w = win32api.GetSystemMetrics(0)
                screen_h = win32api.GetSystemMetrics(1)
                x = 0 if action == "snap_left" else screen_w // 2
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.MoveWindow(hwnd, x, 0, screen_w // 2, screen_h, True)
            else:
                return False
            return True
        except Exception:
            return False

    def launch(self, executable: str) -> bool:
        try:
            subprocess.Popen(executable, shell=True)
            return True
        except Exception:
            return False

    def position_onscreen_keyboard(self, normalized_x: float = 0.5, normalized_y: float = 0.5) -> bool:
        """Move the native Windows OSK near the tracked hands without leaving the screen."""
        if not self.available:
            return False
        try:
            matches: list[int] = []

            def callback(hwnd: int, _extra: Any) -> None:
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return
                    title = win32gui.GetWindowText(hwnd).strip().lower()
                    class_name = win32gui.GetClassName(hwnd).strip().lower()
                    if class_name == "oskmainclass" or "on-screen keyboard" in title:
                        matches.append(hwnd)
                except Exception:
                    return

            win32gui.EnumWindows(callback, None)
            if not matches:
                return False
            hwnd = matches[0]
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(720, right - left)
            height = max(260, bottom - top)
            user32 = ctypes.windll.user32
            screen_left = user32.GetSystemMetrics(76)
            screen_top = user32.GetSystemMetrics(77)
            screen_width = max(1, user32.GetSystemMetrics(78))
            screen_height = max(1, user32.GetSystemMetrics(79))
            hand_x = screen_left + int(clamp(normalized_x, 0.0, 1.0) * screen_width)
            hand_y = screen_top + int(clamp(normalized_y, 0.0, 1.0) * screen_height)
            x = int(clamp(hand_x - width // 2, screen_left, screen_left + screen_width - width))
            y = hand_y + 45
            if y + height > screen_top + screen_height:
                y = hand_y - height - 45
            y = int(clamp(y, screen_top, screen_top + screen_height - height))
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.MoveWindow(hwnd, x, y, width, height, True)
            return True
        except Exception:
            return False

    def move_cursor(self, dx: int, dy: int) -> None:
        if not self.available:
            return
        try:
            x, y = win32api.GetCursorPos()
            win32api.SetCursorPos((x + dx, y + dy))
        except Exception:
            pass

    def set_cursor_position(self, normalized_x: float, normalized_y: float) -> None:
        """Map a camera point to the complete Windows virtual desktop."""
        if not self.available:
            return
        try:
            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
            width = max(1, user32.GetSystemMetrics(78))
            height = max(1, user32.GetSystemMetrics(79))
            x = left + int(clamp(normalized_x, 0.0, 1.0) * (width - 1))
            y = top + int(clamp(normalized_y, 0.0, 1.0) * (height - 1))
            win32api.SetCursorPos((x, y))
        except Exception:
            pass

    def get_cursor_pos(self) -> Optional[tuple[int, int]]:
        if not self.available:
            return None
        try:
            x, y = win32api.GetCursorPos()
            return int(x), int(y)
        except Exception:
            return None

    def set_cursor_pixels(self, x: int, y: int) -> None:
        if not self.available:
            return
        try:
            win32api.SetCursorPos((int(x), int(y)))
        except Exception:
            pass

    def move_cursor_relative(self, normalized_dx: float, normalized_dy: float) -> None:
        """Move relative to the current cursor using the virtual desktop size."""
        if not self.available:
            return
        if not self.cursor_lock.acquire(blocking=False):      # a key press is in progress
            return
        try:
            user32 = ctypes.windll.user32
            width = max(1, user32.GetSystemMetrics(78))
            height = max(1, user32.GetSystemMetrics(79))
            dx = int(round(normalized_dx * width))
            dy = int(round(normalized_dy * height))
            if dx or dy:
                self.move_cursor(dx, dy)
        except Exception:
            pass
        finally:
            self.cursor_lock.release()

    @staticmethod
    def _send_mouse_flags(*flags: int) -> bool:
        if not IS_WINDOWS:
            return False

        pointer_type = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", pointer_type),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("mi", MouseInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("data",)
            _fields_ = [("type", ctypes.c_ulong), ("data", InputUnion)]

        events = (Input * len(flags))()
        for index, flag in enumerate(flags):
            events[index].type = 0  # INPUT_MOUSE
            events[index].mi = MouseInput(0, 0, 0, flag, 0, 0)
        try:
            sent = ctypes.windll.user32.SendInput(
                len(events), ctypes.byref(events), ctypes.sizeof(Input)
            )
            return sent == len(events)
        except Exception:
            return False

    @staticmethod
    def _post_click_to_target(double: bool = False) -> bool:
        """Send a real button sequence to the window below the cursor."""
        if not IS_WINDOWS or not WIN32_AVAILABLE:
            return False
        try:
            point = win32api.GetCursorPos()
            hwnd = win32gui.WindowFromPoint(point)
            if not hwnd:
                return False
            client_x, client_y = win32gui.ScreenToClient(hwnd, point)
            lparam = ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            if double:
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, lparam)
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            return True
        except Exception:
            return False

    @staticmethod
    def _caption_action_at_cursor() -> bool:
        """Handle Windows title-bar buttons, which are not normal client controls."""
        if not IS_WINDOWS or not WIN32_AVAILABLE:
            return False
        try:
            point = win32api.GetCursorPos()
            target = win32gui.WindowFromPoint(point)
            root = int(ctypes.windll.user32.GetAncestor(int(target), 2)) or int(target)  # GA_ROOT
            if not root or not win32gui.IsWindow(root):
                return False
            class_name = win32gui.GetClassName(root)
            if class_name in {"Progman", "WorkerW", "Shell_TrayWnd"}:
                return False

            screen_lparam = ((point[1] & 0xFFFF) << 16) | (point[0] & 0xFFFF)
            hit = int(win32gui.SendMessage(root, win32con.WM_NCHITTEST, 0, screen_lparam))
            if hit == win32con.HTCLOSE:
                win32gui.PostMessage(root, win32con.WM_CLOSE, 0, 0)
                return True
            if hit == win32con.HTMINBUTTON:
                win32gui.ShowWindow(root, win32con.SW_MINIMIZE)
                return True
            if hit == win32con.HTMAXBUTTON:
                action = win32con.SW_RESTORE if win32gui.IsZoomed(root) else win32con.SW_MAXIMIZE
                win32gui.ShowWindow(root, action)
                return True

            # Chromium and some custom Windows 11 title bars do not report
            # HTCLOSE to synthetic hit tests. Use a conservative top-right
            # close zone as a fallback.
            left, top, right, bottom = win32gui.GetWindowRect(root)
            caption_height = max(36, int(ctypes.windll.user32.GetSystemMetrics(4) * 1.8))
            close_width = max(48, int(ctypes.windll.user32.GetSystemMetrics(30) * 1.25))
            if win32gui.GetWindowText(root).strip() and right - close_width <= point[0] <= right and top <= point[1] <= top + caption_height:
                win32gui.PostMessage(root, win32con.WM_CLOSE, 0, 0)
                return True
        except Exception:
            return False
        return False

    def click(self) -> bool:
        if not self.available:
            return False
        if self._post_click_to_target(double=False):
            return True
        return self._send_mouse_flags(0x0002, 0x0004)

    @staticmethod
    def cursor_over_onscreen_keyboard() -> bool:
        if not IS_WINDOWS or not WIN32_AVAILABLE:
            return False
        try:
            point = win32api.GetCursorPos()
            target = win32gui.WindowFromPoint(point)
            root = int(ctypes.windll.user32.GetAncestor(int(target), 2)) or int(target)
            if not root or not win32gui.IsWindow(root):
                return False
            class_name = win32gui.GetClassName(root).strip().lower()
            title = win32gui.GetWindowText(root).strip().lower()
            return class_name == "oskmainclass" or "on-screen keyboard" in title
        except Exception:
            return False

    @staticmethod
    def _find_onscreen_keyboard() -> Optional[int]:
        """Cheap lookup of the native Windows On-Screen Keyboard window (no window enumeration)."""
        if not IS_WINDOWS or not WIN32_AVAILABLE:
            return None
        try:
            hwnd = win32gui.FindWindow("OSKMainClass", None) or win32gui.FindWindow(None, "On-Screen Keyboard")
            if hwnd and win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
                return int(hwnd)
        except Exception:
            pass
        return None

    @staticmethod
    def onscreen_keyboard_rect() -> Optional[tuple[int, int, int, int]]:
        hwnd = WindowsController._find_onscreen_keyboard()
        if hwnd is None:
            return None
        try:
            return win32gui.GetWindowRect(hwnd)
        except Exception:
            return None

    last_click_error = ""

    def click_screen_point(self, x: int, y: int) -> bool:
        """Press a key of the On-Screen Keyboard with a REAL mouse click at (x, y), then put the
        mouse pointer back where the user had it (so the mouse never seems to freeze or jump).

        The OSK decides which key was pressed from the real mouse position, so the pointer is moved
        onto the key first. Posted window messages (used before) did not move the cursor and the
        keyboard ignored or mis-targeted them."""
        if not self.available:
            return False
        rect = self.onscreen_keyboard_rect()
        if rect is None:
            self.last_click_error = "OSK window not found"
            return False
        left, top, right, bottom = rect
        x = int(clamp(x, left + 3, right - 3))      # edge of the mapping area = outer keys, never outside the OSK
        y = int(clamp(y, top + 3, bottom - 3))
        with self.cursor_lock:
            try:
                before = win32api.GetCursorPos()
            except Exception:
                before = None
            try:
                if before is None or abs(before[0] - x) > 4 or abs(before[1] - y) > 4:
                    win32api.SetCursorPos((x, y))
                    time.sleep(0.035)             # let the OSK register the hover on the new key
                    win32api.SetCursorPos((x, y))
                    time.sleep(0.010)
            except Exception as exc:
                self.last_click_error = f"SetCursorPos failed: {exc}"
                return False
            down = self._send_mouse_flags(0x0002)
            time.sleep(0.025)
            up = self._send_mouse_flags(0x0004)
            if down and not up:
                up = self._send_mouse_flags(0x0004)      # never leave the button pressed
            ok = bool(down and up)
            if ok:
                self.last_click_error = ""
            else:
                self.last_click_error = "SendInput failed (is the focused app running as Administrator?)"
            time.sleep(0.015)
            if before is not None:
                try:
                    win32api.SetCursorPos((int(before[0]), int(before[1])))
                except Exception:
                    pass
            if ok:
                return True
        return self._post_click_to_target(double=False)

    @staticmethod
    def click_onscreen_keyboard_at(normalized_x: float, normalized_y: float) -> bool:
        rect = WindowsController.onscreen_keyboard_rect()
        if rect is None or not WIN32_AVAILABLE:
            return False
        left, top, right, bottom = rect
        x = left + int(clamp(normalized_x, 0.0, 1.0) * max(1, right - left - 1))
        y = top + int(clamp(normalized_y, 0.0, 1.0) * max(1, bottom - top - 1))
        try:
            target = win32gui.WindowFromPoint((x, y))
            if not target:
                return False
            client_x, client_y = win32gui.ScreenToClient(target, (x, y))
            lparam = ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)
            win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lparam)
            return True
        except Exception:
            return False

    def double_click(self) -> bool:
        if not self.available:
            return False
        if self._caption_action_at_cursor():
            return True
        if self._post_click_to_target(double=True):
            return True
        first = self._send_mouse_flags(0x0002, 0x0004)
        time.sleep(0.07)
        second = self._send_mouse_flags(0x0002, 0x0004)
        return first and second


class AIClient:
    """Phase 4: OpenAI-compatible endpoint with a safe local fallback."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._history: list[dict[str, str]] = []
        self._history_lock = threading.Lock()
        self._history_limit = 12
        self._supabase_warned = False
        self._session: dict[str, Any] = {}

    @staticmethod
    def supabase_config() -> dict[str, str]:
        return {"url": SUPABASE_PROJECT_URL, "key": SUPABASE_PUBLISHABLE_KEY}

    @classmethod
    def save_supabase_config(cls, url: str, key: str) -> None:
        return None

    @classmethod
    def auth_request(cls, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = cls.supabase_config()
        if not config["url"] or not config["key"]:
            raise ValueError("NEXUS Supabase connection is not configured in this build.")
        if not config["url"].startswith("https://"):
            raise ValueError("Supabase Project URL must start with https://")
        request = urllib.request.Request(
            f"{config['url']}/auth/v1/{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"apikey": config["key"], "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                message = detail.get("msg") or detail.get("message") or detail.get("error_description") or detail.get("error")
            except Exception:
                message = None
            raise RuntimeError(str(message or f"Supabase request failed ({exc.code}).")) from exc

    def set_session(self, session: Optional[dict[str, Any]]) -> None:
        self._session = session or {}
        with self._history_lock:
            self._history.clear()

    def _sync_profile(self) -> None:
        user = self._session.get("user") or {}
        user_id = user.get("id")
        if not user_id:
            return
        try:
            self._supabase_request(
                "POST",
                {"user_id": user_id, "email": user.get("email", ""), "updated_at": datetime.now().astimezone().isoformat()},
                table="nexus_profiles",
                on_conflict="user_id",
            )
        except Exception as exc:
            air_log(f"Supabase profile sync failed: {type(exc).__name__}: {exc}")

    def _supabase_request(
        self,
        method: str,
        payload: Optional[dict[str, Any]] = None,
        table: str = "nexus_messages",
        on_conflict: str = "",
    ) -> Any:
        config = self.supabase_config()
        project_url, anon_key = config["url"], config["key"]
        if not project_url or not anon_key:
            return None
        if not project_url.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS.")
        access_token = self._session.get("access_token")
        user = self._session.get("user") or {}
        user_id = user.get("id")
        if not access_token or not user_id:
            return None
        query_args = {"user_id": f"eq.{user_id}", "order": "created_at.asc"} if method in {"GET", "DELETE"} else {}
        if on_conflict:
            query_args["on_conflict"] = on_conflict
        query = urllib.parse.urlencode(query_args)
        url = f"{project_url}/rest/v1/{table}" + (f"?{query}" if query else "")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal,resolution=merge-duplicates" if on_conflict else "return=minimal",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None

    def _load_remote_memory(self) -> None:
        if self._history:
            return
        try:
            rows = self._supabase_request("GET")
            if isinstance(rows, list):
                self._history = [
                    {"role": row["role"], "content": row["content"]}
                    for row in rows[-self._history_limit:]
                    if row.get("role") in {"user", "assistant"} and isinstance(row.get("content"), str)
                ]
        except Exception as exc:
            if not self._supabase_warned:
                air_log(f"Supabase history load failed: {type(exc).__name__}: {exc}")
                self._supabase_warned = True

    def clear_memory(self) -> None:
        with self._history_lock:
            self._history.clear()
        try:
            self._supabase_request("DELETE")
        except Exception as exc:
            air_log(f"Supabase history clear failed: {type(exc).__name__}: {exc}")

    def memory_size(self) -> int:
        with self._history_lock:
            return len(self._history) // 2

    def _memory_snapshot(self) -> list[dict[str, str]]:
        with self._history_lock:
            return [dict(item) for item in self._history]

    def _remember(self, user_message: str, assistant_message: str) -> None:
        with self._history_lock:
            self._history.extend([
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ])
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]
        try:
            records = [
                {"user_id": (self._session.get("user") or {}).get("id"), "role": role, "content": content}
                for role, content in (("user", user_message), ("assistant", assistant_message))
            ]
            if records[0]["user_id"]:
                self._supabase_request("POST", records)
        except Exception as exc:
            if not self._supabase_warned:
                air_log(f"Supabase history save failed: {type(exc).__name__}: {exc}")
                self._supabase_warned = True

    @property
    def configured(self) -> bool:
        endpoint = self.effective_endpoint
        local_endpoint = "localhost" in endpoint or "127.0.0.1" in endpoint
        return bool(endpoint and self.effective_model and (self.effective_key or local_endpoint))

    @property
    def effective_endpoint(self) -> str:
        return (
            self.settings.ai_endpoint.strip()
            or os.environ.get("JARVIS_AI_ENDPOINT", "").strip()
            or DEFAULT_AI_ENDPOINT
        )

    @property
    def effective_model(self) -> str:
        model = (
            self.settings.ai_model.strip()
            or os.environ.get("JARVIS_AI_MODEL", "").strip()
            or DEFAULT_AI_MODEL
        )
        return DEFAULT_AI_MODEL if model == "gemini-3.5-flash-lite" else model

    @property
    def effective_key(self) -> str:
        return (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("JARVIS_AI_API_KEY", "").strip()
            or self.settings.ai_key.strip()
        )

    def chat(
        self,
        message: str,
        system_prompt: str = "",
        max_output_tokens: Optional[int] = None,
        clean: bool = True,
        use_memory: bool = True,
    ) -> str:
        message = message.strip()
        if not message:
            return "Type a question or command."
        if not self.configured:
            return self.local_response(message)

        if use_memory:
            self._load_remote_memory()
        history = self._memory_snapshot() if use_memory else []
        endpoint = self.effective_endpoint.rstrip("/")
        if "generativelanguage.googleapis.com" in endpoint:
            result = self._chat_gemini_native(message, system_prompt, max_output_tokens, clean, history)
        else:
            result = self._chat_openai_compatible(message, system_prompt, max_output_tokens, clean, history)
        if use_memory and result and not result.startswith("AI connection error:"):
            self._remember(message, result)
        return result

    @staticmethod
    def _normalize_gemini_endpoint(endpoint: str) -> str:
        endpoint = endpoint.rstrip("/")
        for suffix in ("/openai/chat/completions", "/chat/completions", "/openai"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)].rstrip("/")
        if endpoint.endswith("/v1") or endpoint.endswith("/v1beta"):
            return endpoint
        return DEFAULT_AI_ENDPOINT

    def _chat_gemini_native(
        self,
        message: str,
        system_prompt: str = "",
        max_output_tokens: Optional[int] = None,
        clean: bool = True,
        history: Optional[list[dict[str, str]]] = None,
    ) -> str:
        endpoint = self._normalize_gemini_endpoint(self.effective_endpoint)
        model = self.effective_model
        key = self.effective_key
        url = f"{endpoint}/models/{urllib.parse.quote(model, safe='')}:generateContent"
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": str(item.get("content", ""))}],
            }
            for item in (history or [])
            if item.get("content")
        ]
        contents.append({"role": "user", "parts": [{"text": message}]})
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": system_prompt
                        or current_jarvis_prompt()
                    }
                ]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.35,
                "maxOutputTokens": max_output_tokens or AI_MAX_OUTPUT_TOKENS,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts).strip()
            if not text:
                return self.local_response(message)
            return self._clean_assistant_text(text) if clean else text
        except urllib.error.HTTPError as exc:
            return self._http_error_text(exc, message)
        except Exception as exc:
            return f"AI connection error: {exc}\n\nLocal fallback:\n{self.local_response(message)}"

    def _chat_openai_compatible(
        self,
        message: str,
        system_prompt: str = "",
        max_output_tokens: Optional[int] = None,
        clean: bool = True,
        history: Optional[list[dict[str, str]]] = None,
    ) -> str:
        endpoint = self.effective_endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = {
            "model": self.effective_model,
            "messages": (
                [{"role": "system", "content": system_prompt or current_jarvis_prompt()}]
                + [dict(item) for item in (history or [])]
                + [{"role": "user", "content": message}]
            ),
            "temperature": 0.55,
        }
        if max_output_tokens:
            payload["max_tokens"] = max_output_tokens
        headers = {"Content-Type": "application/json"}
        if self.effective_key:
            headers["Authorization"] = f"Bearer {self.effective_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            return self._clean_assistant_text(text) if clean else text
        except urllib.error.HTTPError as exc:
            return self._http_error_text(exc, message)
        except Exception as exc:
            return f"AI connection error: {exc}\n\nLocal fallback:\n{self.local_response(message)}"

    def _http_error_text(self, exc: urllib.error.HTTPError, message: str) -> str:
        details = ""
        try:
            details = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            details = ""
        if details:
            details = details[:900]
            return f"AI connection error: HTTP {exc.code}\n{details}\n\nLocal fallback:\n{self.local_response(message)}"
        return f"AI connection error: HTTP {exc.code}: {exc.reason}\n\nLocal fallback:\n{self.local_response(message)}"

    def project_plan(self, request: str) -> dict[str, Any]:
        request = request.strip()
        if not request:
            raise ValueError("Describe what ULTRON should build.")
        if not self.configured:
            return local_starter_plan(request)

        system_prompt = (
            "You are the planning engine inside ULTRON Mission Builder. "
            "Create a small, complete, runnable project for the user's request. "
            "Return only one valid JSON object with this exact schema: "
            '{"project_name":"short_name","summary":"one sentence","run_file":"relative/path",'
            '"files":[{"path":"relative/path","content":"complete text content"}]}. '
            "Use only relative file paths. Include all source files and a README with exact run instructions. "
            "Create at most 12 text files. Do not include binary data, secrets, API keys, destructive scripts, "
            "credential theft, persistence, evasion, or commands that alter files outside the project folder. "
            "Do not use markdown fences or add commentary outside the JSON."
        )
        response = self.chat(
            request,
            system_prompt,
            max_output_tokens=4096,
            clean=False,
            use_memory=False,
        )
        if response.startswith("AI connection error:"):
            raise RuntimeError(response.split("\n", 1)[0])
        return normalize_project_plan(json_object_from_text(response), request)

    @staticmethod
    def _clean_assistant_text(text: str) -> str:
        lines = [line.strip().lstrip("-*• ").strip() for line in text.splitlines()]
        return " ".join(line for line in lines if line).strip()

    @staticmethod
    def local_response(message: str) -> str:
        low = message.lower()
        now = datetime.now()
        if any(word in low for word in ["help", "commands", "what can you do"]):
            return "I can control Windows, create complete local projects, build ZIP packages, manage files and answer with Gemini. Say build project to start a mission."
        if any(word in low for word in ["your name", "who are you"]):
            return "I am ULTRON, your Windows assistant."
        if any(word in low for word in ["time", "what time"]):
            return f"The time is {now.strftime('%H:%M:%S')}."
        if any(word in low for word in ["weather"]):
            return "Weather is not fully connected yet. I can open the weather window, and later we can add live data."
        if any(word in low for word in ["summarize"]):
            clean = " ".join(message.split())
            return clean[:420] + ("…" if len(clean) > 420 else "")
        if any(word in low for word in ["rewrite"]):
            return "I can help in a simple way now, but full rewriting needs Gemini to be connected."
        return "I am here. You can ask a question or tell me what to open on the computer."


class AIWorker(QThread):
    finished_text = Signal(str)

    def __init__(self, client: AIClient, message: str, system_prompt: str = ""):
        super().__init__()
        self.client = client
        self.message = message
        self.system_prompt = system_prompt

    def run(self) -> None:
        self.finished_text.emit(self.client.chat(self.message, self.system_prompt))


class ProjectPlanWorker(QThread):
    planned = Signal(object)
    failed = Signal(str)

    def __init__(self, client: AIClient, request: str):
        super().__init__()
        self.client = client
        self.request = request

    def run(self) -> None:
        try:
            self.planned.emit(self.client.project_plan(self.request))
        except Exception as exc:
            self.failed.emit(str(exc))


class WeatherWorker(QThread):
    finished_data = Signal(dict)
    failed = Signal(str)

    def __init__(self, city: str):
        super().__init__()
        self.city = city

    def run(self) -> None:
        try:
            geo_url = (
                "https://geocoding-api.open-meteo.com/v1/search?"
                + urllib.parse.urlencode({"name": self.city, "count": 1, "language": "en", "format": "json"})
            )
            with urllib.request.urlopen(geo_url, timeout=15) as response:
                geo = json.loads(response.read().decode("utf-8"))
            if not geo.get("results"):
                raise RuntimeError("City not found")
            place = geo["results"][0]
            weather_url = (
                "https://api.open-meteo.com/v1/forecast?"
                + urllib.parse.urlencode({
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "timezone": "auto",
                })
            )
            with urllib.request.urlopen(weather_url, timeout=15) as response:
                weather = json.loads(response.read().decode("utf-8"))
            self.finished_data.emit({"place": place, "current": weather.get("current", {})})
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceWorker(QThread):
    heard = Signal(str)
    failed = Signal(str)

    @staticmethod
    def _choose_recognition_result(results: list[tuple[str, str]]) -> str:
        if not results:
            return ""
        by_lang = {language: text.strip() for language, text in results if text.strip()}
        english = by_lang.get("en-US", "")
        if english:
            return english
        return results[0][1].strip()

    def _recognize_from_microphone(self) -> str:
        """Capture one complete utterance from the default Windows microphone."""
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

        chunk_seconds = 0.05
        chunk_frames = max(1, int(sample_rate * chunk_seconds))
        max_wait_seconds = 5.0
        max_speech_seconds = max(4.0, min(7.0, VOICE_RECORD_SECONDS))
        trailing_silence_seconds = 0.65
        speech_rms = 0.0035
        speech_peak = 0.020
        silence_rms = 0.0025
        silence_peak = 0.012
        pre_roll: deque[np.ndarray] = deque(maxlen=max(1, int(0.25 / chunk_seconds)))
        utterance: list[np.ndarray] = []
        speech_started = False
        silent_for = 0.0
        waited_for = 0.0
        spoken_for = 0.0

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=chunk_frames,
            ) as stream:
                while waited_for < max_wait_seconds and spoken_for < max_speech_seconds:
                    block, _ = stream.read(chunk_frames)
                    samples = np.asarray(block, dtype=np.float32).reshape(-1).copy()
                    if samples.size == 0:
                        continue
                    centered = samples - float(np.mean(samples))
                    peak = float(np.max(np.abs(centered)))
                    rms = float(np.sqrt(np.mean(centered * centered)))

                    if not speech_started:
                        pre_roll.append(samples)
                        waited_for += chunk_seconds
                        if rms >= speech_rms or peak >= speech_peak:
                            speech_started = True
                            utterance.extend(pre_roll)
                            pre_roll.clear()
                        continue

                    utterance.append(samples)
                    spoken_for += chunk_seconds
                    if rms < silence_rms and peak < silence_peak:
                        silent_for += chunk_seconds
                        if spoken_for >= 0.35 and silent_for >= trailing_silence_seconds:
                            break
                    else:
                        silent_for = 0.0
        except Exception as exc:
            raise RuntimeError(f"Microphone could not start: {exc}")

        if not speech_started or not utterance:
            raise RuntimeError("No speech recognized.")

        samples = np.concatenate(utterance).astype(np.float32, copy=False)
        if samples.size == 0:
            raise RuntimeError("Microphone returned no audio.")

        # Remove DC offset and amplify quiet microphones without clipping.
        samples = samples - float(np.mean(samples))
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

        if peak < 0.002 or rms < 0.0004:
            raise RuntimeError("No speech recognized.")

        target_peak = 0.85
        gain = min(12.0, target_peak / max(peak, 1e-6))
        samples = np.clip(samples * gain, -1.0, 1.0)
        pcm16 = (samples * 32767.0).astype(np.int16).tobytes()

        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 2.5
        audio = sr.AudioData(pcm16, sample_rate, 2)

        errors: list[str] = []
        results: list[tuple[str, str]] = []

        def recognize(language: str) -> tuple[str, str, str]:
            try:
                result = recognizer.recognize_google(audio, language=language)
                if result and result.strip():
                    return language, result.strip(), ""
                return language, "", f"No {language} speech recognized"
            except sr.UnknownValueError:
                return language, "", f"No {language} speech recognized"
            except sr.RequestError as exc:
                return language, "", f"Speech service error: {exc}"
            except Exception as exc:
                return language, "", str(exc)

        # English-only recognition keeps the response path faster.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            futures = [executor.submit(recognize, "en-US")]
            try:
                for future in concurrent.futures.as_completed(futures, timeout=3.5):
                    language, result, error = future.result()
                    if result:
                        results.append((language, result))
                    elif error:
                        errors.append(error)
            except concurrent.futures.TimeoutError:
                errors.append("Speech recognition timed out")

        choice = self._choose_recognition_result(results)
        if choice:
            return choice

        raise RuntimeError("; ".join(errors) or "No speech recognized.")

    def _recognize_windows(self) -> str:
        if not IS_WINDOWS:
            raise RuntimeError("Windows speech fallback requires Windows.")
        windir = os.environ.get("WINDIR", r"C:\\Windows")
        powershell = os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.exists(powershell):
            powershell = "powershell.exe"
        ps_script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
if (-not $installed -or $installed.Count -eq 0) { throw 'No Windows speech recognizer is installed.' }
$choice = $installed | Where-Object { $_.Culture.Name -eq 'en-US' } | Select-Object -First 1
if (-not $choice) { $choice = $installed | Select-Object -First 1 }
$recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($choice)
$recognizer.SetInputToDefaultAudioDevice()
$grammar = [System.Speech.Recognition.DictationGrammar]::new()
$recognizer.LoadGrammar($grammar)
$result = $recognizer.Recognize([TimeSpan]::FromSeconds(4))
if ($result -and $result.Text) { Write-Output $result.Text } else { throw 'No speech recognized.' }
$recognizer.Dispose()
"""
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=7, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
        )
        if completed.returncode == 0 and (completed.stdout or "").strip():
            return completed.stdout.strip().splitlines()[-1].strip()
        raise RuntimeError((completed.stderr or "Windows speech failed").strip()[-500:])

    def run(self) -> None:
        errors = []
        try:
            text = self._recognize_from_microphone()
            self.heard.emit(text)
            return
        except Exception as exc:
            errors.append(f"Direct mic: {exc}")

        try:
            text = self._recognize_windows()
            self.heard.emit(text)
            return
        except Exception as exc:
            errors.append(f"Windows fallback: {exc}")

        self.failed.emit(" | ".join(errors))




class SpeechWorker(QThread):
    """Speak assistant replies without blocking the HoloDesk UI.

    Windows TTS order:
      1) Gemini TTS -- highest-quality cloud voice when GEMINI_API_KEY is set.
      2) Edge neural TTS -- natural no-extra-key fallback.
      3) SAPI.SpVoice COM -- reliable on normal Windows desktops.
      4) System.Speech.Synthesis fallback.
    """
    finished_speaking = Signal()
    failed = Signal(str)
    engine_used = Signal(str)

    def __init__(self, text: str):
        super().__init__()
        self.original_text = (text or "").strip()
        self.text = self._make_speakable(self.original_text)
        self.edge_text = self._edge_speakable_text(self.original_text)

    @staticmethod
    def _has_armenian(text: str) -> bool:
        return any("\u0531" <= char <= "\u058f" for char in text)

    @classmethod
    def _edge_speakable_text(cls, text: str) -> str:
        return text or ""

    @staticmethod
    def _make_speakable(text: str) -> str:
        return text

    def _powershell_path(self) -> str:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        classic = os.path.join(
            windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        return classic if os.path.exists(classic) else "powershell.exe"

    def _run_ps(self, script: str, timeout: int = 60) -> tuple[bool, str]:
        completed = subprocess.run(
            [
                self._powershell_path(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            input=self.text,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
        )
        if completed.returncode == 0:
            return True, ""
        return False, (completed.stderr or completed.stdout or "TTS failed").strip()[-900:]

    def _play_audio_file(self, audio_path: Path, timeout: int = 60) -> tuple[bool, str]:
        uri = audio_path.resolve().as_uri()
        escaped_uri = uri.replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore
$player = [System.Windows.Media.MediaPlayer]::new()
$player.Open([Uri]'{escaped_uri}')
$player.Volume = 1
$player.Play()
$deadline = [DateTime]::Now.AddSeconds({int(timeout)})
while (-not $player.NaturalDuration.HasTimeSpan -and [DateTime]::Now -lt $deadline) {{
    Start-Sleep -Milliseconds 100
}}
if ($player.NaturalDuration.HasTimeSpan) {{
    $sleepMs = [Math]::Min([int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 350, {int(timeout)} * 1000)
    Start-Sleep -Milliseconds $sleepMs
}} else {{
    Start-Sleep -Seconds 3
}}
$player.Stop()
$player.Close()
"""
        return self._run_ps(script, timeout=timeout + 5)

    def _write_wave_file(
        self,
        filename: Path,
        pcm: bytes,
        channels: int = 1,
        rate: int = 24000,
        sample_width: int = 2,
    ) -> None:
        with wave.open(str(filename), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm)

    @staticmethod
    def _find_audio_data(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            output_audio = value.get("output_audio") or value.get("outputAudio")
            if isinstance(output_audio, dict) and isinstance(output_audio.get("data"), str):
                return output_audio["data"]
            inline_data = value.get("inlineData") or value.get("inline_data")
            if isinstance(inline_data, dict) and isinstance(inline_data.get("data"), str):
                return inline_data["data"]
            for item in value.values():
                found = SpeechWorker._find_audio_data(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = SpeechWorker._find_audio_data(item)
                if found:
                    return found
        return None

    def _run_gemini_tts(self) -> tuple[bool, str]:
        key = (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("JARVIS_AI_API_KEY", "").strip()
        )
        if not key:
            return False, "GEMINI_API_KEY is not set."

        text = self.original_text.strip()
        if not text:
            return True, ""

        model = os.environ.get("JARVIS_GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview").strip()
        voice = os.environ.get("JARVIS_GEMINI_TTS_VOICE", "Charon").strip() or "Charon"
        prompt = (
            "Speak in a deep, controlled, metallic synthetic AI voice. Be precise, cold, "
            "and subtly intimidating, without imitating any real person or actor. "
            "Keep the same language as the transcript. Do not add extra words.\n\n"
            f"Transcript: {text}"
        )
        fd, raw_path = tempfile.mkstemp(prefix="jarvis_gemini_voice_", suffix=".wav")
        os.close(fd)
        audio_path = Path(raw_path)

        try:
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
            with urllib.request.urlopen(request, timeout=GEMINI_TTS_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))

            audio_data = self._find_audio_data(data)
            if not audio_data:
                return False, "Gemini did not return audio."

            pcm = base64.b64decode(audio_data)
            self._write_wave_file(audio_path, pcm)
            return self._play_audio_file(audio_path, timeout=EDGE_TTS_TIMEOUT_SECONDS)
        except Exception as exc:
            return False, str(exc)
        finally:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _run_edge_tts(self) -> tuple[bool, str]:
        try:
            import edge_tts
        except Exception as exc:
            return False, "edge-tts is not installed: " + str(exc)

        text = self.edge_text.strip()
        if not text:
            return True, ""

        voice = os.environ.get("JARVIS_EDGE_VOICE", "en-US-GuyNeural").strip() or "en-US-GuyNeural"
        rate = os.environ.get("JARVIS_EDGE_RATE", "-6%").strip() or "-6%"
        pitch = os.environ.get("JARVIS_EDGE_PITCH", "-20Hz").strip() or "-20Hz"
        fd, raw_path = tempfile.mkstemp(prefix="jarvis_voice_", suffix=".mp3")
        os.close(fd)
        audio_path = Path(raw_path)

        try:
            async def save_voice() -> None:
                communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
                await communicate.save(str(audio_path))

            import asyncio
            asyncio.run(asyncio.wait_for(save_voice(), timeout=EDGE_TTS_TIMEOUT_SECONDS))
            return self._play_audio_file(audio_path, timeout=EDGE_TTS_TIMEOUT_SECONDS)
        except Exception as exc:
            return False, str(exc)
        finally:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass

    def run(self) -> None:
        if not self.original_text:
            self.finished_speaking.emit()
            return

        if not IS_WINDOWS:
            self.failed.emit("Speech output requires Windows.")
            self.finished_speaking.emit()
            return

        errors = []

        if VOICE_PRIORITY in {"gemini", "quality"}:
            try:
                ok, err = self._run_gemini_tts()
                if ok:
                    self.engine_used.emit("Gemini voice")
                    self.finished_speaking.emit()
                    return
                errors.append("Gemini voice: " + err)
            except Exception as exc:
                errors.append("Gemini voice: " + str(exc))

        # Fast mode uses Edge first. It is more likely to stay under 3-5s.
        try:
            ok, err = self._run_edge_tts()
            if ok:
                self.engine_used.emit("Edge neural voice")
                self.finished_speaking.emit()
                return
            errors.append("Edge neural voice: " + err)
        except Exception as exc:
            errors.append("Edge neural voice: " + str(exc))

        if VOICE_PRIORITY not in {"gemini", "quality"}:
            try:
                ok, err = self._run_gemini_tts()
                if ok:
                    self.engine_used.emit("Gemini voice")
                    self.finished_speaking.emit()
                    return
                errors.append("Gemini voice: " + err)
            except Exception as exc:
                errors.append("Gemini voice: " + str(exc))

        # 3) SAPI.SpVoice -- uses the normal Windows desktop speech/audio path.
        sapi_script = r"""
$ErrorActionPreference = 'Stop'
$text = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }

$voice = New-Object -ComObject SAPI.SpVoice
$voice.Volume = 100
$voice.Rate = -2

# Prefer a deeper male Windows voice when one is installed.
try {
    $voices = @($voice.GetVoices())
    if ($voices.Count -gt 0) {
        $preferred = $voices | Where-Object {
            $_.GetDescription() -match 'David|Mark|Guy|Male'
        } | Select-Object -First 1
        $voice.Voice = if ($preferred) { $preferred } else { $voices[0] }
    }
} catch {}

[void]$voice.Speak($text, 0)
"""
        try:
            ok, err = self._run_ps(sapi_script, timeout=EDGE_TTS_TIMEOUT_SECONDS)
            if ok:
                self.engine_used.emit("Windows SAPI voice")
                self.finished_speaking.emit()
                return
            errors.append("SAPI: " + err)
        except Exception as exc:
            errors.append("SAPI: " + str(exc))

        # 4) .NET System.Speech fallback.
        dotnet_script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }

$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$synth.Volume = 100
$synth.Rate = -2
try {
    $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Male)
} catch {}
$synth.SetOutputToDefaultAudioDevice()
$synth.Speak($text)
$synth.Dispose()
"""
        try:
            ok, err = self._run_ps(dotnet_script, timeout=EDGE_TTS_TIMEOUT_SECONDS)
            if ok:
                self.engine_used.emit("Windows fallback voice")
                self.finished_speaking.emit()
                return
            errors.append("System.Speech: " + err)
        except Exception as exc:
            errors.append("System.Speech: " + str(exc))

        self.failed.emit(" | ".join(errors) or "Windows TTS failed.")
        self.finished_speaking.emit()


class VoiceAIWorker(QThread):
    answered = Signal(str)

    def __init__(self, client: AIClient, question: str):
        super().__init__()
        self.client = client
        self.question = question

    def run(self) -> None:
        prompt = current_jarvis_prompt() + " The assistant is in English-only mode. Reply only in English."
        try:
            self.answered.emit(self.client.chat(self.question, prompt))
        except Exception as exc:
            self.answered.emit(f"I could not answer the question. {exc}")


class JarvisVoiceController(QObject):
    """Always-on ULTRON voice assistant for NEXUS."""
    status_changed = Signal(str)

    def __init__(self, canvas: "HoloCanvas", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.canvas = canvas
        self.worker: Optional[VoiceWorker] = None
        self.speaker: Optional[SpeechWorker] = None
        self.ai_worker: Optional[VoiceAIWorker] = None
        self.enabled = True
        self._closing = False
        self._restart_delay_ms = 120
        self._last_error = ""
        self._busy_reply = False

        # Rate-limit / loop protection.
        self._last_heard_norm = ""
        self._last_heard_at = 0.0
        self._last_spoken_norm = ""
        self._last_spoken_at = 0.0
        self._last_user_language = "en"
        self._ai_cooldown_until = 0.0
        self._duplicate_window_sec = 8.0
        self._self_echo_window_sec = 7.0
        self._rate_limit_cooldown_sec = 45.0

        QTimer.singleShot(100, self._start_listening)

    def _start_listening(self) -> None:
        if not self.enabled or self._closing or self._busy_reply:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.status_changed.emit("ULTRON • LISTENING")
        self.worker = VoiceWorker()
        self.worker.heard.connect(self._heard)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(text.lower().replace("-", " ").replace("_", " ").split())

    def _command_reply(self, text: str) -> tuple[bool, str]:
        n = self._norm(text)
        command_words = set(n.split())
        def has(*items: str) -> bool:
            return contains_phrase(n, *items)

        # Wake / greeting.
        if n in {"hello ultron", "hey ultron", "hi ultron", "ultron"}:
            return True, "Hello Alex. ULTRON is online."
        if has("clear memory", "forget conversation", "forget our conversation"):
            self.canvas.ai_client.clear_memory()
            return True, "Conversation memory cleared."
        if has("help", "commands", "what can you do"):
            return True, "I can control Windows and build complete local projects with files and a ZIP. Say build project to begin."
        if has("what is your name", "who are you"):
            return True, "I am ULTRON, your local Windows assistant."
        if "time" in command_words or has("what time is it"):
            return True, f"The time is {datetime.now().strftime('%H:%M')}."
        if project_generation_intent(n):
            ok = self.canvas.execute_command(text, silent=True)
            if ok:
                return True, "I am generating a random app." if random_app_intent(n) else "I am generating the app."
            return True, "I could not start the app generator."

        mappings = [
            (("open chrome",), "Chrome is open."),
            (("open notepad", "notepad"), "Notepad is open."),
            (("open calculator", "open calc", "calc", "calculator"), "Calculator is open."),
            (("open windows browser", "windows browser", "open default browser", "default browser"), "Windows browser is open."),
            (("open browser", "open brauzer", "open brouser", "open bowser", "browser", "brauzer", "brouser"), "NEXUS browser is open."),
            (("open ai", "ai assistant"), "AI Assistant is open."),
            (("world map", "digital twin", "my world"), "World Map is open."),
            (("future self", "future simulator", "simulate future"), "Future Self simulator is open."),
            (("zip builder", "make zip", "build zip", "create zip", "package files"), "ZIP Builder is open."),
            (("generate a random app", "generate random app", "make a random app", "make random app", "create a random app", "create random app"), "I am generating a random app."),
            (("mission builder", "build project", "create project", "make project", "generate app", "build app", "create app"), "Mission Builder is open."),
            (("self edit", "self editor", "edit yourself", "change yourself"), "Self Edit Center is open."),
            (("windows manager", "window manager"), "Window Manager is open."),
            (("notes", "note"), "Notes are open."),
            (("calendar",), "Calendar is open."),
            (("weather",), "Weather is open."),
            (("clock",), "Clock is open."),
            (("video",), "Video is open."),
            (("music",), "Music is open."),
            (("phone",), "Phone window is open."),
            (("open keyboard", "show keyboard", "on screen keyboard"), "Windows keyboard is open."),
            (("air menu",), "Air Menu is open."),
            (("close window",), "Window closed."),
            (("maximize",), "Window maximized."),
            (("minimize",), "Window minimized."),
            (("restore",), "Window restored."),
            (("snap left",), "Window moved left."),
            (("snap right",), "Window moved right."),
        ]
        for phrases, reply in mappings:
            if has(*phrases):
                ok = self.canvas.execute_command(text, silent=True)
                if ok:
                    return True, reply
                return True, "I could not run that command."
        return False, ""

    def _heard(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return

        now = time.monotonic()
        norm = self._norm(clean)

        # Ignore the same recognition result for a few seconds. This prevents
        # one spoken sentence from being submitted to the API multiple times.
        if norm and norm == self._last_heard_norm and (now - self._last_heard_at) < self._duplicate_window_sec:
            self.status_changed.emit("VOICE • DUPLICATE IGNORED")
            return

        # Ignore ULTRON hearing its own TTS immediately after speaking.
        if norm and self._last_spoken_norm and (now - self._last_spoken_at) < self._self_echo_window_sec:
            if norm == self._last_spoken_norm or norm in self._last_spoken_norm or self._last_spoken_norm in norm:
                self.status_changed.emit("VOICE • SELF-ECHO IGNORED")
                return

        self._last_heard_norm = norm
        self._last_heard_at = now
        self._last_user_language = choose_language(clean)
        self.status_changed.emit(f"VOICE • HEARD: {clean[:64]}")
        try:
            reactor = getattr(self.canvas, "reactor_console", None)
            if reactor is not None and hasattr(reactor, "log"):
                reactor.log("HEARD", clean)
        except Exception:
            pass

        handled, reply = self._command_reply(clean)
        if handled:
            self._speak(reply)
            return

        # If the API recently returned 429, do not keep retrying every time the
        # microphone produces a result.
        if now < self._ai_cooldown_until:
            remaining = max(1, int(self._ai_cooldown_until - now))
            self.status_changed.emit(f"AI • COOLDOWN {remaining}s")
            return

        if self.ai_worker is not None and self.ai_worker.isRunning():
            self.status_changed.emit("AI • BUSY")
            return

        # Unknown speech is treated as a question for ULTRON.
        self._busy_reply = True
        self.status_changed.emit("AI • THINKING")
        self.ai_worker = VoiceAIWorker(self.canvas.ai_client, clean)
        self.ai_worker.answered.connect(self._ai_answered)
        self.ai_worker.finished.connect(self._ai_finished)
        self.ai_worker.start()

    def _ai_answered(self, answer: str) -> None:
        answer = (answer or "").strip()
        if not answer:
            answer = "I could not find an answer."

        lowered = answer.lower()
        if "http error 429" in lowered or "too many requests" in lowered or "rate_limit" in lowered or "insufficient_quota" in lowered:
            self._ai_cooldown_until = time.monotonic() + self._rate_limit_cooldown_sec
            self.status_changed.emit(f"AI • RATE LIMIT • WAIT {int(self._rate_limit_cooldown_sec)}s")
            self._speak("The request limit was reached. Wait a little, then try again.")
            return

        if "ai connection error" in lowered or "http " in lowered:
            self.status_changed.emit(f"AI • ERROR: {answer[:90]}")
            self._speak("I could not connect to Gemini. Try again in a moment.")
            return

        self.status_changed.emit(f"AI • ANSWER: {answer[:64]}")
        self._speak(answer)

    def _ai_finished(self) -> None:
        worker = self.ai_worker
        self.ai_worker = None
        if worker is not None:
            worker.deleteLater()

    def _speak(self, text: str) -> None:
        self._busy_reply = True
        self._last_spoken_norm = self._norm(text)
        self._last_spoken_at = time.monotonic()
        self.status_changed.emit(f"ULTRON • SPEAKING: {text[:64]}")
        self.speaker = SpeechWorker(text)
        self.speaker.engine_used.connect(lambda engine: self.status_changed.emit(f"VOICE ENGINE • {engine}"))
        self.speaker.failed.connect(lambda e: self.status_changed.emit(f"TTS ERROR • {e[:90]}"))
        self.speaker.finished_speaking.connect(self._speech_finished)
        self.speaker.start()

    def _speech_finished(self) -> None:
        speaker = self.speaker
        self.speaker = None
        if speaker is not None:
            speaker.deleteLater()
        self._busy_reply = False
        if self.enabled and not self._closing:
            QTimer.singleShot(150, self._start_listening)

    def _failed(self, error: str) -> None:
        lowered = (error or "").lower()
        quiet_cases = (
            "no speech recognized",
            "no hy-am speech recognized",
            "no en-us speech recognized",
            "unknownvalue",
        )
        if any(token in lowered for token in quiet_cases):
            self._last_error = ""
            self.status_changed.emit("ULTRON • LISTENING")
            return
        self._last_error = error
        self.status_changed.emit(f"VOICE ERROR • {error[:120]}")

    def _finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        if self.enabled and not self._closing and not self._busy_reply:
            QTimer.singleShot(self._restart_delay_ms, self._start_listening)

    def stop(self) -> None:
        self.enabled = False
        self._closing = True
        self.status_changed.emit("VOICE • OFF")


class CompanionState:
    def __init__(self):
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.latest_camera_jpeg: Optional[bytes] = None
        self.lock = threading.Lock()
        self.token = secrets.token_hex(8)
        self.failures: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.monotonic()
        with self.lock:
            recent = [t for t in self.failures.get(ip, []) if now - t < 120.0]
            self.failures[ip] = recent
            return len(recent) >= 8

    def register_failure(self, ip: str) -> None:
        with self.lock:
            self.failures.setdefault(ip, []).append(time.monotonic())


COMPANION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>HoloDesk Companion</title><style>
body{margin:0;background:#061019;color:#dffaff;font-family:Arial,sans-serif;overflow:hidden}header{padding:14px 16px;border-bottom:1px solid #237a95;background:#0b1e2a}h2{margin:0;font-size:19px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}button{padding:14px;border:1px solid #36a9c9;border-radius:12px;background:#12394b;color:#eaffff;font-weight:700}#pad{height:42vh;margin:12px;border:1px solid #36a9c9;border-radius:18px;background:radial-gradient(circle,#123849,#081923);touch-action:none;display:flex;align-items:center;justify-content:center;color:#68aabd}.cam{padding:12px}video{width:100%;max-height:22vh;border-radius:12px;background:#000}.small{font-size:12px;color:#83aeb9}</style></head>
<body><header><h2>HoloDesk Companion</h2><div class="small">Touchpad • Remote • Phone camera</div></header>
<div id="pad">TOUCHPAD</div><div class="grid">
<button onclick="sendCmd('click')">Click</button><button onclick="sendCmd('air_menu')">Air Menu</button>
<button onclick="sendCmd('browser')">Browser</button><button onclick="sendCmd('ai')">AI Assistant</button>
<button onclick="sendCmd('maximize')">Maximize</button><button onclick="sendCmd('close_window')">Close Window</button>
<button onclick="sendCmd('save_workspace')">Save Workspace</button><button onclick="sendCmd('next_monitor')">Next Monitor</button>
</div><div class="cam"><video id="video" autoplay muted playsinline></video><button style="width:100%;margin-top:8px" onclick="startCamera()">Start phone camera</button><input id="photo" type="file" accept="image/*" capture="environment" style="width:100%;margin-top:8px" onchange="uploadPhoto(this.files[0])"></div>
<script>
const token=new URLSearchParams(location.search).get('token')||'';
function post(path,data){fetch(path+'?token='+encodeURIComponent(token),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).catch(()=>{});}
function sendCmd(command){post('/event',{type:'command',command});}
const pad=document.getElementById('pad');let last=null;
pad.addEventListener('pointerdown',e=>{last={x:e.clientX,y:e.clientY};pad.setPointerCapture(e.pointerId)});
pad.addEventListener('pointermove',e=>{if(!last)return;let dx=e.clientX-last.x,dy=e.clientY-last.y;last={x:e.clientX,y:e.clientY};post('/event',{type:'move',dx,dy});});
pad.addEventListener('pointerup',()=>last=null);pad.addEventListener('dblclick',()=>sendCmd('click'));
async function startCamera(){try{const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});const v=document.getElementById('video');v.srcObject=stream;const c=document.createElement('canvas');setInterval(()=>{if(!v.videoWidth)return;c.width=320;c.height=240;c.getContext('2d').drawImage(v,0,0,320,240);c.toBlob(b=>{if(b)fetch('/camera?token='+encodeURIComponent(token),{method:'POST',body:b})},'image/jpeg',.55)},700)}catch(e){alert('Live camera needs browser permission/secure context. Use the camera file control below as a fallback.')}}
function uploadPhoto(file){if(file)fetch('/camera?token='+encodeURIComponent(token),{method:'POST',body:file}).catch(()=>{});}
</script></body></html>'''


class CompanionServer:
    """Phase 9: local mobile web companion (touchpad, remote and camera stream)."""

    def __init__(self, state: CompanionState):
        self.state = state
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port = 0

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self, port: int) -> tuple[bool, str]:
        if self.running:
            return True, self.url()
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def _authorized(self) -> bool:
                ip = self.client_address[0]
                if state.blocked(ip):
                    return False
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                supplied = query.get("token", [""])[0]
                if hmac.compare_digest(supplied.encode("utf-8"), state.token.encode("utf-8")):
                    return True
                state.register_failure(ip)
                return False

            def _send(self, status: int, data: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                path = urllib.parse.urlparse(self.path).path
                if path == "/":
                    self._send(200, COMPANION_HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/camera.jpg" and self._authorized():
                    with state.lock:
                        data = state.latest_camera_jpeg
                    if data:
                        self._send(200, data, "image/jpeg")
                    else:
                        self._send(404, b"No frame", "text/plain")
                else:
                    self._send(404, b"Not found", "text/plain")

            def do_POST(self) -> None:
                if not self._authorized():
                    self._send(403, b"Forbidden", "text/plain")
                    return
                path = urllib.parse.urlparse(self.path).path
                length = safe_int(self.headers.get("Content-Length"), 0)
                body = self.rfile.read(min(length, 2_000_000))
                if path == "/event":
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        state.events.put(payload)
                        self._send(200, b"OK", "text/plain")
                    except Exception:
                        self._send(400, b"Bad JSON", "text/plain")
                elif path == "/camera":
                    with state.lock:
                        state.latest_camera_jpeg = body
                    state.events.put({"type": "camera"})
                    self._send(200, b"OK", "text/plain")
                else:
                    self._send(404, b"Not found", "text/plain")

            def log_message(self, format: str, *args: Any) -> None:
                return

        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            self.port = self.server.server_address[1]
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return True, self.url()
        except Exception as exc:
            self.server = None
            return False, str(exc)

    def url(self) -> str:
        return f"http://{local_ip()}:{self.port}/?token={self.state.token}"

    def stop(self) -> None:
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
        self.server = None
        self.thread = None


class ImageView(QLabel):
    def __init__(self, path: str = ""):
        super().__init__()
        self.path = path
        self.original = QPixmap(path) if path else QPixmap()
        self.angle = 0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: rgba(4, 8, 14, 230); color:#9FC9D5;")
        self.update_pixmap()

    def rotate_by(self, degrees: int) -> None:
        self.angle = (self.angle + degrees) % 360
        self.update_pixmap()

    def update_pixmap(self) -> None:
        if self.original.isNull():
            self.setText("Image unavailable")
            return
        rotated = self.original.transformed(QTransform().rotate(self.angle), Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(rotated.scaled(
            max(100, self.width() - 16), max(80, self.height() - 16),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event) -> None:
        self.update_pixmap()
        super().resizeEvent(event)


class ResizeHandle(QFrame):
    def __init__(self, owner: "VirtualWindow"):
        super().__init__(owner)
        self.owner = owner
        self.dragging = False
        self.start_global = QPoint()
        self.start_size = QSize()
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet("background: rgba(104,225,255,120); border-bottom-right-radius:8px;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.start_global = event.globalPosition().toPoint()
            self.start_size = self.owner.size()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.dragging:
            delta = event.globalPosition().toPoint() - self.start_global
            self.owner.resize(
                max(self.owner.minimumWidth(), self.start_size.width() + delta.x()),
                max(self.owner.minimumHeight(), self.start_size.height() + delta.y()),
            )
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.dragging = False
        event.accept()


class VirtualWindow(QFrame):
    def __init__(
        self,
        canvas: "HoloCanvas",
        title: str,
        content_widget: QWidget,
        width: int = 390,
        height: int = 270,
        content_type: str = "generic",
        content_data: Optional[dict[str, Any]] = None,
    ):
        super().__init__(canvas)
        self.canvas = canvas
        self.content_widget = content_widget
        self.content_type = content_type
        self.content_data = content_data or {}
        self.dragging = False
        self.drag_offset = QPoint()
        self.normal_geometry = QRect(80, 100, width, height)
        self.maximized = False
        self.minimized = False
        self.rotation_angle = 0
        self.window_id = f"w-{int(time.time() * 1000)}-{random.randint(100,999)}"
        self.setObjectName("virtualWindow")
        self.setMinimumSize(250, 150)
        self.resize(width, height)
        self._apply_style()

        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(34)
        glow.setOffset(0, 4)
        glow.setColor(QColor(40, 205, 255, 105))
        self.setGraphicsEffect(glow)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.titlebar = QFrame()
        self.titlebar.setFixedHeight(38)
        self.titlebar.setStyleSheet("""
            QFrame { background: rgba(13, 43, 59, 238); border-top-left-radius:15px; border-top-right-radius:15px; }
            QPushButton { color:#DDF9FF; background:transparent; border:none; border-radius:7px; font-weight:700; }
            QPushButton:hover { background:rgba(255,255,255,35); }
        """)
        title_layout = QHBoxLayout(self.titlebar)
        title_layout.setContentsMargins(11, 0, 6, 0)
        title_layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color:#EAFBFF;font-weight:700;")
        self.state_label = QLabel("")
        self.state_label.setStyleSheet("color:#72CFE8;font-size:10px;")
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.state_label)
        title_layout.addStretch()

        for label, callback in [
            ("—", self.minimize_window),
            ("□", self.toggle_maximize),
            ("×", self.close),
        ]:
            button = QPushButton(label)
            button.setFixedSize(27, 26)
            button.clicked.connect(callback)
            title_layout.addWidget(button)

        root.addWidget(self.titlebar)
        root.addWidget(content_widget, 1)
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.raise_()
        self.show()
        self.fade_in()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QFrame#virtualWindow {
                background: rgba(11, 18, 29, 244);
                border: 1px solid rgba(86, 224, 255, 190);
                border-radius: 16px;
            }
        """)

    def fade_in(self) -> None:
        self.setWindowOpacity(0.3)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(260)
        animation.setStartValue(0.3)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_animation = animation

    def title(self) -> str:
        return self.title_label.text()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= self.titlebar.height():
            self.raise_()
            self.canvas.active_window = self
            self.dragging = True
            self.drag_offset = event.position().toPoint()
            if self.maximized:
                self.restore_window()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.position().y() <= self.titlebar.height():
            self.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.dragging:
            global_point = event.globalPosition().toPoint()
            parent_point = self.canvas.mapFromGlobal(global_point) - self.drag_offset
            self.move_clamped(parent_point.x(), parent_point.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.dragging = False
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        self.resize_handle.move(self.width() - 19, self.height() - 19)
        super().resizeEvent(event)

    def move_clamped(self, x: int, y: int) -> None:
        self.move(
            int(clamp(x, 0, max(0, self.canvas.width() - self.width()))),
            int(clamp(y, 72, max(72, self.canvas.height() - self.height()))),
        )

    def minimize_window(self) -> None:
        if self.minimized:
            self.restore_window()
            return
        self.normal_geometry = self.geometry()
        self.minimized = True
        self.maximized = False
        self.content_widget.hide()
        self.setFixedHeight(40)
        self.state_label.setText("MIN")

    def toggle_maximize(self) -> None:
        if self.maximized:
            self.restore_window()
        else:
            self.maximize_window()

    def maximize_window(self) -> None:
        if not self.maximized:
            self.normal_geometry = self.geometry()
        self.setMinimumSize(250, 150)
        self.setMaximumSize(16777215, 16777215)
        self.content_widget.show()
        self.minimized = False
        self.maximized = True
        self.setGeometry(8, 78, max(300, self.canvas.width() - 16), max(200, self.canvas.height() - 86))
        self.state_label.setText("MAX")
        self.raise_()
        self.canvas.active_window = self

    def restore_window(self) -> None:
        self.setMinimumSize(250, 150)
        self.setMaximumSize(16777215, 16777215)
        self.content_widget.show()
        self.minimized = False
        self.maximized = False
        self.setGeometry(self.normal_geometry)
        self.state_label.setText("")
        self.move_clamped(self.x(), self.y())

    def snap_left(self) -> None:
        self.normal_geometry = self.geometry()
        self.setGeometry(8, 78, max(280, self.canvas.width() // 2 - 12), max(200, self.canvas.height() - 86))
        self.minimized = False
        self.maximized = False
        self.content_widget.show()
        self.state_label.setText("LEFT")

    def snap_right(self) -> None:
        width = max(280, self.canvas.width() // 2 - 12)
        self.normal_geometry = self.geometry()
        self.setGeometry(self.canvas.width() - width - 8, 78, width, max(200, self.canvas.height() - 86))
        self.minimized = False
        self.maximized = False
        self.content_widget.show()
        self.state_label.setText("RIGHT")

    def rotate_by(self, degrees: int) -> None:
        self.rotation_angle = (self.rotation_angle + degrees) % 360
        if isinstance(self.content_widget, ImageView):
            self.content_widget.rotate_by(degrees)
        self.state_label.setText(f"{self.rotation_angle}°")
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            rad = math.radians(self.rotation_angle)
            effect.setOffset(math.cos(rad) * 7, math.sin(rad) * 7)

    def serialize(self) -> dict[str, Any]:
        geometry = self.normal_geometry if self.minimized else self.geometry()
        data = dict(self.content_data)
        if self.content_type in {"text", "notes"} and isinstance(self.content_widget, QTextEdit):
            data["text"] = self.content_widget.toPlainText()
        return {
            "title": self.title(),
            "type": self.content_type,
            "data": data,
            "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            "rotation": self.rotation_angle,
            "maximized": self.maximized,
        }

    def closeEvent(self, event) -> None:
        self.canvas.unregister_window(self)
        super().closeEvent(event)


class CalculatorWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.display = QLineEdit()
        self.display.setPlaceholderText("2 + 2 * 5")
        self.display.returnPressed.connect(self.calculate)
        layout.addWidget(self.display)
        grid = QGridLayout()
        buttons = ["7", "8", "9", "/", "4", "5", "6", "*", "1", "2", "3", "-", "0", ".", "(", ")", "C", "⌫", "+", "="]
        for index, text in enumerate(buttons):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, t=text: self.press(t))
            grid.addWidget(button, index // 4, index % 4)
        layout.addLayout(grid)
        self.setStyleSheet(button_style() + input_style())

    def press(self, text: str) -> None:
        if text == "C":
            self.display.clear()
        elif text == "⌫":
            self.display.setText(self.display.text()[:-1])
        elif text == "=":
            self.calculate()
        else:
            self.display.insert(text)

    @staticmethod
    def safe_eval(expression: str) -> float:
        allowed_binops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a ** b,
        }
        allowed_unary = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}

        def visit(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_binops:
                return allowed_binops[type(node.op)](visit(node.left), visit(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
                return allowed_unary[type(node.op)](visit(node.operand))
            raise ValueError("Unsupported expression")

        tree = ast.parse(expression, mode="eval")
        return visit(tree)

    def calculate(self) -> None:
        try:
            result = self.safe_eval(self.display.text())
            self.display.setText(str(int(result)) if result.is_integer() else str(round(result, 10)))
        except Exception:
            self.display.setText("Error")


class ClockWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.clock = QLCDNumber()
        self.clock.setDigitCount(8)
        self.clock.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
        self.clock.setStyleSheet("color:#8BE9FF;background:rgba(4,9,15,220);border:none;")
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_label.setStyleSheet("color:#CDEFF8;font-size:16px;")
        layout.addWidget(self.clock, 1)
        layout.addWidget(self.date_label)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now()
        self.clock.display(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A, %d %B %Y"))


class WeatherWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.worker: Optional[WeatherWorker] = None
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.city = QLineEdit("Yerevan")
        button = QPushButton("Load")
        button.clicked.connect(self.load_weather)
        row.addWidget(self.city, 1)
        row.addWidget(button)
        self.result = QLabel("Enter a city and load current weather.")
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setStyleSheet("color:#DDF7FF;font-size:16px;padding:15px;")
        layout.addLayout(row)
        layout.addWidget(self.result, 1)
        self.setStyleSheet(button_style() + input_style())

    def load_weather(self) -> None:
        city = self.city.text().strip()
        if not city:
            return
        self.result.setText("Loading…")
        self.worker = WeatherWorker(city)
        self.worker.finished_data.connect(self.show_weather)
        self.worker.failed.connect(lambda error: self.result.setText(f"Weather error: {error}"))
        self.worker.start()

    def show_weather(self, data: dict) -> None:
        place = data["place"]
        current = data["current"]
        self.result.setText(
            f"{place.get('name')}, {place.get('country', '')}\n\n"
            f"Temperature: {current.get('temperature_2m', '—')} °C\n"
            f"Feels like: {current.get('apparent_temperature', '—')} °C\n"
            f"Wind: {current.get('wind_speed_10m', '—')} km/h\n"
            f"Weather code: {current.get('weather_code', '—')}"
        )


class BrowserWidget(QWidget):
    def __init__(self, url: str = "https://www.google.com"):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.address = QLineEdit(url)
        go = QPushButton("Go")
        back = QPushButton("←")
        forward = QPushButton("→")
        reload_btn = QPushButton("↻")
        row.addWidget(back)
        row.addWidget(forward)
        row.addWidget(reload_btn)
        row.addWidget(self.address, 1)
        row.addWidget(go)
        layout.addLayout(row)
        if WEBENGINE_AVAILABLE:
            self.view = QWebEngineView()
            self.view.setUrl(QUrl(url))
            layout.addWidget(self.view, 1)
            go.clicked.connect(self.navigate)
            self.address.returnPressed.connect(self.navigate)
            back.clicked.connect(self.view.back)
            forward.clicked.connect(self.view.forward)
            reload_btn.clicked.connect(self.view.reload)
            self.view.urlChanged.connect(lambda value: self.address.setText(value.toString()))
        else:
            self.view = QLabel("Qt WebEngine is unavailable. Use Open External Browser.")
            self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.view, 1)
            go.setText("Open External")
            go.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromUserInput(self.address.text())))
            back.setEnabled(False)
            forward.setEnabled(False)
            reload_btn.setEnabled(False)
        self.setStyleSheet(button_style() + input_style())

    def navigate(self) -> None:
        if WEBENGINE_AVAILABLE:
            self.view.setUrl(QUrl.fromUserInput(self.address.text()))


class MediaWidget(QWidget):
    def __init__(self, kind: str = "video"):
        super().__init__()
        self.kind = kind
        self.media_path = ""
        layout = QVBoxLayout(self)
        self.status = QLabel(f"Choose a {kind} file")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color:#D7F5FC;padding:10px;")
        if MULTIMEDIA_AVAILABLE:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            if kind == "video":
                self.video = QVideoWidget()
                self.player.setVideoOutput(self.video)
                layout.addWidget(self.video, 1)
            else:
                self.art = QLabel("♫")
                self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.art.setStyleSheet("font-size:70px;color:#8BE9FF;background:rgba(4,9,15,220);")
                layout.addWidget(self.art, 1)
        else:
            self.player = None
            layout.addWidget(self.status, 1)
        controls = QHBoxLayout()
        open_btn = QPushButton("Open")
        play_btn = QPushButton("Play / Pause")
        stop_btn = QPushButton("Stop")
        open_btn.clicked.connect(self.choose_file)
        play_btn.clicked.connect(self.toggle_play)
        stop_btn.clicked.connect(lambda: self.player.stop() if self.player else None)
        controls.addWidget(open_btn)
        controls.addWidget(play_btn)
        controls.addWidget(stop_btn)
        layout.addWidget(self.status)
        layout.addLayout(controls)
        self.setStyleSheet(button_style())

    def choose_file(self) -> None:
        filters = "Videos (*.mp4 *.mkv *.avi *.mov *.webm)" if self.kind == "video" else "Audio (*.mp3 *.wav *.m4a *.ogg *.flac)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose media", "", filters)
        if not path:
            return
        self.media_path = path
        self.status.setText(Path(path).name)
        if self.player:
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()

    def toggle_play(self) -> None:
        if not self.player:
            self.status.setText("Qt Multimedia is unavailable.")
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()


class AIChatWidget(QWidget):
    def __init__(self, client: AIClient, canvas: "HoloCanvas"):
        super().__init__()
        self.client = client
        self.canvas = canvas
        self.worker: Optional[AIWorker] = None
        layout = QVBoxLayout(self)
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setHtml("<b style='color:#FF9A45'>ULTRON:</b> NEXUS assistant online.")
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask AI or type a desktop command…")
        send = QPushButton("Send")
        screen = QPushButton("Screen")
        clip = QPushButton("Clipboard AI")
        clear = QPushButton("Clear Memory")
        send.clicked.connect(self.send_message)
        self.input.returnPressed.connect(self.send_message)
        screen.clicked.connect(self.screen_context)
        clip.clicked.connect(self.clipboard_ai)
        clear.clicked.connect(self.clear_memory)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        row.addWidget(screen)
        row.addWidget(clip)
        row.addWidget(clear)
        layout.addWidget(self.history, 1)
        layout.addLayout(row)
        self.setStyleSheet(button_style() + input_style())

    def append(self, who: str, text: str) -> None:
        color = "#FF9A45" if who == "ULTRON" else "#FFE08A"
        self.history.append(f"<b style='color:{color}'>{who}:</b> {text.replace(chr(10), '<br>')}")

    def clear_memory(self) -> None:
        self.client.clear_memory()
        self.history.clear()
        self.append("ULTRON", "Conversation memory cleared.")

    def send_message(self) -> None:
        message = self.input.text().strip()
        if not message:
            return
        self.input.clear()
        self.append("YOU", message)
        if self.canvas.execute_command(message, silent=True):
            self.append("ULTRON", "Command executed.")
            return
        self.worker = AIWorker(self.client, message)
        self.worker.finished_text.connect(lambda text: self.append("ULTRON", text))
        self.worker.start()

    def screen_context(self) -> None:
        context = self.canvas.screen_context()
        self.append("SCREEN", context)
        self.worker = AIWorker(self.client, f"Analyze this desktop context and suggest the next useful action:\n{context}")
        self.worker.finished_text.connect(lambda text: self.append("ULTRON", text))
        self.worker.start()

    def clipboard_ai(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.append("ULTRON", "Clipboard is empty.")
            return
        instruction, ok = QInputDialog.getItem(
            self, "Clipboard AI", "Action", ["Summarize", "Rewrite professionally", "Translate to English", "Extract tasks"], 0, False
        )
        if not ok:
            return
        self.append("YOU", f"{instruction}: [clipboard]")
        self.worker = AIWorker(self.client, f"{instruction}:\n\n{text}")
        self.worker.finished_text.connect(self._clipboard_result)
        self.worker.start()

    def _clipboard_result(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.append("ULTRON", text + "<br><i>Copied to clipboard.</i>")


class WindowsManagerWidget(QWidget):
    def __init__(self, controller: WindowsController):
        super().__init__()
        self.controller = controller
        self.rows: list[dict[str, Any]] = []
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setStyleSheet("color:#9ED7E5;")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Application", "Window", "PID", "State"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        controls = QGridLayout()
        actions = [
            ("Refresh", self.refresh), ("Bring Front", lambda: self.perform("front")),
            ("Minimize", lambda: self.perform("minimize")), ("Maximize", lambda: self.perform("maximize")),
            ("Restore", lambda: self.perform("restore")), ("Close", lambda: self.perform("close")),
            ("Snap Left", lambda: self.perform("snap_left")), ("Snap Right", lambda: self.perform("snap_right")),
        ]
        for index, (label, callback) in enumerate(actions):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button, index // 4, index % 4)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addLayout(controls)
        self.setStyleSheet(button_style() + "QTableWidget{background:#08131D;color:#DDF7FF;gridline-color:#1D5365;}QHeaderView::section{background:#123241;color:#DDF7FF;padding:6px;}")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def refresh(self) -> None:
        if not self.controller.available:
            self.status.setText("Real Windows integration is available only on Windows with pywin32 installed.")
            self.table.setRowCount(0)
            return
        selected_hwnd = self.selected_hwnd()
        self.rows = self.controller.list_windows()
        self.table.setRowCount(len(self.rows))
        selected_row = -1
        for row_index, row in enumerate(self.rows):
            state = "Minimized" if row["minimized"] else "Maximized" if row["maximized"] else "Normal"
            values = [row["process"], row["title"], str(row["pid"]), state]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row["hwnd"])
                self.table.setItem(row_index, column, item)
            if row["hwnd"] == selected_hwnd:
                selected_row = row_index
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.status.setText(f"Detected {len(self.rows)} open windows • live refresh every 1.5 sec")

    def selected_hwnd(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            return 0
        item = self.table.item(row, 0)
        return safe_int(item.data(Qt.ItemDataRole.UserRole) if item else 0)

    def perform(self, action: str) -> None:
        hwnd = self.selected_hwnd()
        if not hwnd:
            self.status.setText("Select a window first.")
            return
        ok = self.controller.bring_to_front(hwnd) if action == "front" else self.controller.action(hwnd, action)
        self.status.setText("Action completed." if ok else "Action failed or was blocked by Windows.")
        QTimer.singleShot(250, self.refresh)


class VoiceControlWidget(QWidget):
    def __init__(self, canvas: "HoloCanvas"):
        super().__init__()
        self.canvas = canvas
        self.worker: Optional[VoiceWorker] = None
        self.speaker: Optional[SpeechWorker] = None
        layout = QVBoxLayout(self)
        self.status = QLabel("ULTRON voice is always on. You can also type a command or press Listen manually.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#CDEFF8;padding:8px;")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Example: Hey Ultron, open Chrome / time / open notepad")
        row = QHBoxLayout()
        run = QPushButton("Run Command")
        mic = QPushButton("Listen")
        test = QPushButton("Test Voice")
        run.clicked.connect(self.run_command)
        mic.clicked.connect(self.listen)
        test.clicked.connect(lambda: self.speak("ULTRON voice test is working."))
        self.input.returnPressed.connect(self.run_command)
        row.addWidget(run)
        row.addWidget(mic)
        row.addWidget(test)
        examples = QLabel(
            "English: Hey Ultron • Open Chrome • Open Notepad • Open Calculator • Time • Help"
        )
        examples.setWordWrap(True)
        examples.setStyleSheet("color:#7EAFBC;padding:10px;")
        layout.addWidget(self.status)
        layout.addWidget(self.input)
        layout.addLayout(row)
        layout.addWidget(examples)
        layout.addStretch()
        self.setStyleSheet(button_style() + input_style())

    def run_command(self) -> None:
        command = self.input.text().strip()
        if not command:
            return
        ok = self.canvas.execute_command(command)
        if ok:
            reply = "Command executed."
        else:
            reply = self.canvas.ai_client.local_response(command)
        self.status.setText(reply)
        self.speak(reply)

    def listen(self) -> None:
        self.status.setText("Listening for up to 3 seconds...")
        self.worker = VoiceWorker()
        self.worker.heard.connect(self._heard)
        self.worker.failed.connect(lambda error: self.status.setText(f"Voice error: {error}"))
        self.worker.start()

    def _heard(self, text: str) -> None:
        self.input.setText(text)
        self.status.setText(f"Heard: {text}")
        self.run_command()

    def speak(self, text: str) -> None:
        if self.speaker is not None and self.speaker.isRunning():
            self.status.setText("ULTRON is already speaking. Try again in a second.")
            return
        self.speaker = SpeechWorker(text)
        self.speaker.engine_used.connect(lambda engine: self.status.setText(f"Voice engine: {engine}"))
        self.speaker.failed.connect(lambda error: self.status.setText(f"Voice output error: {error}"))
        self.speaker.finished_speaking.connect(self._speech_finished)
        self.speaker.start()

    def _speech_finished(self) -> None:
        speaker = self.speaker
        self.speaker = None
        if speaker is not None:
            speaker.deleteLater()


class PhoneCompanionWidget(QWidget):
    def __init__(self, canvas: "HoloCanvas"):
        super().__init__()
        self.canvas = canvas
        layout = QVBoxLayout(self)
        self.title = QLabel("Use any Android phone browser as a HoloDesk companion.")
        self.title.setWordWrap(True)
        self.url = QLineEdit()
        self.url.setReadOnly(True)
        self.url.setPlaceholderText("Server is stopped")
        row = QHBoxLayout()
        start = QPushButton("Start Companion")
        stop = QPushButton("Stop")
        copy = QPushButton("Copy URL")
        start.clicked.connect(self.start_server)
        stop.clicked.connect(self.stop_server)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.url.text()))
        row.addWidget(start)
        row.addWidget(stop)
        row.addWidget(copy)
        self.camera = QLabel("Phone camera stream will appear here")
        self.camera.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera.setMinimumHeight(180)
        self.camera.setStyleSheet("background:#03070B;color:#7FA6B0;border:1px solid #195267;")
        layout.addWidget(self.title)
        layout.addWidget(self.url)
        layout.addLayout(row)
        layout.addWidget(self.camera, 1)
        self.setStyleSheet(button_style() + input_style())
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_camera)
        self.refresh_timer.start(700)

    def start_server(self) -> None:
        ok, value = self.canvas.start_companion()
        self.url.setText(value if ok else "")
        self.title.setText("Open this URL on a phone connected to the same Wi-Fi." if ok else f"Could not start: {value}")

    def stop_server(self) -> None:
        self.canvas.stop_companion()
        self.url.clear()
        self.title.setText("Companion server stopped.")

    def refresh_camera(self) -> None:
        with self.canvas.companion_state.lock:
            data = self.canvas.companion_state.latest_camera_jpeg
        if not data:
            return
        pix = QPixmap()
        if pix.loadFromData(data, "JPG"):
            self.camera.setPixmap(pix.scaled(self.camera.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class SettingsWidget(QWidget):
    settings_changed = Signal()
    auth_session_changed = Signal(object)
    authenticated = Signal(object)

    def __init__(self, settings: AppSettings):
        super().__init__()
        self.auth_session: Optional[dict[str, Any]] = None
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"AI endpoint settings. Default model: {DEFAULT_AI_MODEL}."))
        self.endpoint = QLineEdit(settings.ai_endpoint)
        self.endpoint.setPlaceholderText(DEFAULT_AI_ENDPOINT)
        self.model = QLineEdit(settings.ai_model)
        self.model.setPlaceholderText(DEFAULT_AI_MODEL)
        self.key = QLineEdit(settings.ai_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Optional API key. Prefer GEMINI_API_KEY environment variable.")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(settings.phone_port)
        form = QGridLayout()
        form.addWidget(QLabel("Endpoint"), 0, 0); form.addWidget(self.endpoint, 0, 1)
        form.addWidget(QLabel("Model"), 1, 0); form.addWidget(self.model, 1, 1)
        form.addWidget(QLabel("API key"), 2, 0); form.addWidget(self.key, 2, 1)
        form.addWidget(QLabel("Phone port"), 3, 0); form.addWidget(self.port, 3, 1)
        save = QPushButton("Save Settings")
        gemini = QPushButton("Use default Gemini")
        save.clicked.connect(self.save)
        gemini.clicked.connect(self.use_gemini_defaults)
        note = QLabel("Leave Endpoint/Model empty to use Gemini defaults. Leave API key empty to read GEMINI_API_KEY from Windows. If no key exists, ULTRON uses local fallback mode.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7FAAB5;")
        auth_form = QGridLayout()
        self.auth_email = QLineEdit()
        self.auth_email.setPlaceholderText("Email")
        self.auth_password = QLineEdit()
        self.auth_password.setPlaceholderText("Password")
        self.auth_password.setEchoMode(QLineEdit.EchoMode.Password)
        auth_form.addWidget(QLabel("Account"), 0, 0)
        auth_form.addWidget(self.auth_email, 0, 1)
        auth_form.addWidget(QLabel("Password"), 1, 0)
        auth_form.addWidget(self.auth_password, 1, 1)
        signup = QPushButton("Create account")
        login = QPushButton("Log in")
        logout = QPushButton("Log out")
        signup.clicked.connect(lambda: self.authenticate(True))
        login.clicked.connect(lambda: self.authenticate(False))
        logout.clicked.connect(self.logout)
        auth_actions = QHBoxLayout()
        auth_actions.addWidget(signup)
        auth_actions.addWidget(login)
        auth_actions.addWidget(logout)
        layout.addLayout(form)
        layout.addWidget(gemini)
        layout.addWidget(save)
        layout.addWidget(QLabel("Register or log in to save your account and chat to the cloud"))
        layout.addLayout(auth_form)
        layout.addLayout(auth_actions)
        layout.addWidget(note)
        layout.addStretch()
        self.setStyleSheet(button_style() + input_style())

    def save(self) -> None:
        endpoint = self.endpoint.text().strip()
        if "generativelanguage.googleapis.com" in endpoint:
            endpoint = AIClient._normalize_gemini_endpoint(endpoint)
        self.settings.ai_endpoint = endpoint
        self.settings.ai_model = self.model.text().strip()
        self.settings.ai_key = self.key.text().strip()
        self.settings.phone_port = self.port.value()
        self.settings.save()
        self.settings_changed.emit()
        QMessageBox.information(self, APP_NAME, "Settings saved.")

    def authenticate(self, signup: bool) -> None:
        try:
            endpoint_value = self.endpoint.text().strip()
            self.settings.ai_endpoint = AIClient._normalize_gemini_endpoint(endpoint_value) if "generativelanguage.googleapis.com" in endpoint_value else endpoint_value
            self.settings.ai_model = self.model.text().strip()
            self.settings.ai_key = self.key.text().strip()
            self.settings.phone_port = self.port.value()
            self.settings.save()
            self.settings_changed.emit()
            email = self.auth_email.text().strip()
            password = self.auth_password.text()
            if not email or not password:
                raise ValueError("Enter your email and password.")
            endpoint = "signup" if signup else "token?grant_type=password"
            result = AIClient.auth_request(endpoint, {"email": email, "password": password})
            if not result.get("access_token"):
                QMessageBox.information(self, APP_NAME, result.get("msg") or "Account created. Check your email to confirm, then log in.")
                return
            self.auth_session = result
            self.auth_session_changed.emit(result)
            self.authenticated.emit(result)
            QMessageBox.information(self, APP_NAME, f"Logged in as {result.get('user', {}).get('email', email)}")
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Supabase account error:\n{exc}")

    def logout(self) -> None:
        self.auth_session = None
        self.auth_session_changed.emit(None)
        self.auth_password.clear()
        QMessageBox.information(self, APP_NAME, "Logged out. Cloud chat is disconnected.")

    def use_gemini_defaults(self) -> None:
        self.endpoint.setText(DEFAULT_AI_ENDPOINT)
        self.model.setText(DEFAULT_AI_MODEL)
        self.key.clear()


class RegistrationGate(QDialog):
    def __init__(self, settings: AppSettings):
        super().__init__(None)
        self.settings = settings
        self.session: Optional[dict[str, Any]] = None
        self.setWindowTitle(f"{APP_NAME} — Account required")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet("QDialog{background:#03080D;color:#EAFBFF;} QLabel{color:#DDF7FF;} QLineEdit{background:#0B1B27;color:#EAFBFF;border:1px solid #28758E;border-radius:10px;padding:14px;font-size:16px;} QPushButton{background:#17495D;color:#EAFBFF;border:1px solid #4EA7C1;border-radius:10px;padding:14px;font-size:16px;font-weight:700;} QPushButton:hover{background:#225C70;}")
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = QFrame()
        card.setMaximumWidth(560)
        card.setStyleSheet("QFrame{background:#0A1A25;border:1px solid #28758E;border-radius:22px;}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 34, 36, 34)
        title = QLabel("NEXUS ULTRON")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:30px;font-weight:800;color:#8BE9FF;border:0;")
        subtitle = QLabel("Create an account or log in to continue")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size:17px;border:0;padding:8px;")
        self.email = QLineEdit()
        self.email.setPlaceholderText("Email")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        create = QPushButton("Create account")
        login = QPushButton("Log in")
        create.clicked.connect(lambda: self.authenticate(True))
        login.clicked.connect(lambda: self.authenticate(False))
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.email)
        layout.addWidget(self.password)
        layout.addWidget(create)
        layout.addWidget(login)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def authenticate(self, signup: bool) -> None:
        try:
            email = self.email.text().strip()
            password = self.password.text()
            if not email or not password:
                raise ValueError("Enter your email and password.")
            endpoint = "signup" if signup else "token?grant_type=password"
            result = AIClient.auth_request(endpoint, {"email": email, "password": password})
            if not result.get("access_token"):
                QMessageBox.information(self, APP_NAME, result.get("msg") or "Account created. Check your email to confirm, then log in.")
                return
            self.session = result
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Account error:\n{exc}")

    def closeEvent(self, event) -> None:
        event.accept()


class WorldMapWidget(QWidget):
    """Personal operating map: projects, goals, devices, ideas and skills."""

    DEFAULTS = {
        "projects": "ULTRON for NEXUS\nEDITH glasses\nHoloDesk",
        "goals": "Make ULTRON useful every day\nImprove English voice speed\nAdd screen awareness",
        "devices": "Windows PC\nMicrophone\nCamera",
        "ideas": "Mission Control\nFuture Self simulator\nCreator Lab",
        "skills": "Python\nAI assistants\nUI design\nWindows automation",
    }

    def __init__(self):
        super().__init__()
        self.editors: dict[str, QTextEdit] = {}
        layout = QVBoxLayout(self)
        title = QLabel("ULTRON WORLD MAP")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:4px;")
        layout.addWidget(title)
        subtitle = QLabel("This is not chat memory. It is your local control map: projects, goals, devices, ideas and skills.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#86B9C8;padding:0 4px 8px 4px;")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        for key, label in [
            ("projects", "Projects"),
            ("goals", "Goals"),
            ("devices", "Devices"),
            ("ideas", "Ideas"),
            ("skills", "Skills"),
        ]:
            editor = QTextEdit()
            editor.setPlaceholderText(f"Write your {label.lower()} here, one per line.")
            editor.setStyleSheet(input_style() + "QTextEdit{font-size:13px;padding:10px;}")
            self.editors[key] = editor
            tabs.addTab(editor, label)
        layout.addWidget(tabs, 1)

        row = QHBoxLayout()
        save = QPushButton("Save Map")
        reset = QPushButton("Load Starter Map")
        copy = QPushButton("Copy Summary")
        save.clicked.connect(self.save)
        reset.clicked.connect(self.load_defaults)
        copy.clicked.connect(self.copy_summary)
        row.addWidget(save)
        row.addWidget(reset)
        row.addWidget(copy)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#7FCDE2;padding:4px;")
        layout.addWidget(self.status)
        self.setStyleSheet(button_style() + input_style() + "QTabWidget::pane{border:1px solid #28758E;} QTabBar::tab{color:#DDF7FF;background:#102A38;padding:8px;}")
        self.load()

    def load(self) -> None:
        data = self.DEFAULTS.copy()
        if WORLD_MAP_PATH.exists():
            try:
                loaded = json.loads(WORLD_MAP_PATH.read_text(encoding="utf-8"))
                data.update({key: str(value) for key, value in loaded.items()})
            except Exception:
                pass
        for key, editor in self.editors.items():
            editor.setPlainText(data.get(key, ""))

    def save(self) -> None:
        data = {key: editor.toPlainText().strip() for key, editor in self.editors.items()}
        WORLD_MAP_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.setText(f"Saved locally: {WORLD_MAP_PATH}")

    def load_defaults(self) -> None:
        for key, value in self.DEFAULTS.items():
            self.editors[key].setPlainText(value)
        self.status.setText("Starter map loaded. Press Save Map to keep it.")

    def copy_summary(self) -> None:
        parts = []
        for key, editor in self.editors.items():
            parts.append(f"{key.upper()}:\n{editor.toPlainText().strip()}")
        QApplication.clipboard().setText("\n\n".join(parts))
        self.status.setText("World Map summary copied.")


class FutureSelfWidget(QWidget):
    """Simulates a simple future timeline from one goal and one daily action."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("FUTURE SELF SIMULATOR")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:4px;")
        layout.addWidget(title)

        form = QGridLayout()
        self.goal = QLineEdit("Build a useful ULTRON assistant")
        self.daily = QLineEdit("Work on it for 45 minutes")
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setValue(30)
        form.addWidget(QLabel("Goal"), 0, 0); form.addWidget(self.goal, 0, 1)
        form.addWidget(QLabel("Daily action"), 1, 0); form.addWidget(self.daily, 1, 1)
        form.addWidget(QLabel("Days"), 2, 0); form.addWidget(self.days, 2, 1)
        layout.addLayout(form)

        row = QHBoxLayout()
        simulate = QPushButton("Simulate")
        seven = QPushButton("7 Days")
        thirty = QPushButton("30 Days")
        ninety = QPushButton("90 Days")
        simulate.clicked.connect(self.simulate)
        seven.clicked.connect(lambda: self.set_days_and_simulate(7))
        thirty.clicked.connect(lambda: self.set_days_and_simulate(30))
        ninety.clicked.connect(lambda: self.set_days_and_simulate(90))
        for button in (simulate, seven, thirty, ninety):
            row.addWidget(button)
        layout.addLayout(row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(input_style() + "QTextEdit{font-size:13px;padding:10px;}")
        layout.addWidget(self.output, 1)

        copy = QPushButton("Copy Timeline")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.output.toPlainText()))
        layout.addWidget(copy)
        self.setStyleSheet(button_style() + input_style() + "QLabel{color:#CFF7FF;}")
        self.simulate()

    def set_days_and_simulate(self, days: int) -> None:
        self.days.setValue(days)
        self.simulate()

    def simulate(self) -> None:
        goal = self.goal.text().strip() or "your goal"
        daily = self.daily.text().strip() or "one focused action"
        days = self.days.value()
        total_hours = round(days * 0.75, 1)
        checkpoints = sorted({1, max(1, days // 4), max(1, days // 2), max(1, days * 3 // 4), days})
        lines = [
            f"Goal: {goal}",
            f"Daily action: {daily}",
            f"Time horizon: {days} days",
            "",
            "Future timeline:",
        ]
        for day in checkpoints:
            progress = int(day / days * 100)
            if day == 1:
                result = "You start the loop and remove the first friction."
            elif day < days // 2:
                result = "The habit becomes easier and the project gets visible structure."
            elif day < days:
                result = "You now have enough progress to test, show, or improve the system."
            else:
                result = "Your future self has a real version, not only an idea."
            lines.append(f"Day {day}: {progress}% - {result}")
        lines.extend([
            "",
            f"Estimated focused time: about {total_hours} hours.",
            "Risk: skipping days silently.",
            "Rule: if you miss a day, do a 10-minute recovery version the next day.",
            "Next action: start one small step now.",
        ])
        self.output.setPlainText("\n".join(lines))


class MissionBuilderWidget(QWidget):
    """Plans a local project, previews it, then writes and packages it with approval."""

    def __init__(self, client: AIClient, initial_request: str = "", auto_start: bool = False):
        super().__init__()
        self.client = client
        self.worker: Optional[ProjectPlanWorker] = None
        self.plan: Optional[dict[str, Any]] = None
        self.last_project: Optional[Path] = None
        self.last_run_file: Optional[Path] = None

        layout = QVBoxLayout(self)
        title = QLabel("ULTRON MISSION BUILDER")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:4px;")
        note = QLabel(
            "Describe a project. ULTRON prepares the files, shows the plan, asks for approval, "
            "then creates the folder and ZIP. Generated projects are never run automatically."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#91C7D4;")
        layout.addWidget(title)
        layout.addWidget(note)

        self.request = QTextEdit()
        self.request.setPlaceholderText(
            "Example: Build a Windows expense tracker with a simple GUI, local JSON storage and a README."
        )
        self.request.setMaximumHeight(105)
        self.request.setPlainText(initial_request.strip())
        layout.addWidget(self.request)

        form = QGridLayout()
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Generated from the plan")
        self.output_folder = QLineEdit(str(PROJECTS_PATH))
        choose = QPushButton("Choose Folder")
        choose.clicked.connect(self.choose_output_folder)
        form.addWidget(QLabel("Project name"), 0, 0)
        form.addWidget(self.project_name, 0, 1, 1, 2)
        form.addWidget(QLabel("Save in"), 1, 0)
        form.addWidget(self.output_folder, 1, 1)
        form.addWidget(choose, 1, 2)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.plan_button = QPushButton("Create Plan")
        self.build_button = QPushButton("Approve, Build and ZIP")
        self.run_button = QPushButton("Run App")
        self.open_button = QPushButton("Open Folder")
        self.build_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.plan_button.clicked.connect(self.create_plan)
        self.build_button.clicked.connect(self.build_project)
        self.run_button.clicked.connect(self.run_result)
        self.open_button.clicked.connect(self.open_result)
        controls.addWidget(self.plan_button)
        controls.addWidget(self.build_button)
        controls.addWidget(self.run_button)
        controls.addWidget(self.open_button)
        layout.addLayout(controls)

        self.status = QLabel("Ready. Gemini creates the full plan when connected; offline mode creates a starter project.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#72D7F2;padding:4px;")
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("The project plan and file list will appear here.")
        layout.addWidget(self.status)
        layout.addWidget(self.preview, 1)
        self.setStyleSheet(button_style() + input_style() + "QLabel{color:#CFF7FF;}")
        if initial_request.strip() and auto_start:
            QTimer.singleShot(350, self.create_plan)

    def choose_output_folder(self) -> None:
        current = self.output_folder.text().strip() or str(PROJECTS_PATH)
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder", current)
        if folder:
            self.output_folder.setText(folder)

    def create_plan(self) -> None:
        request = self.request.toPlainText().strip()
        if not request:
            QMessageBox.information(self, APP_NAME, "Describe what ULTRON should build first.")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.plan = None
        self.build_button.setEnabled(False)
        self.plan_button.setEnabled(False)
        self.preview.clear()
        self.status.setText("ULTRON is designing the project and preparing complete files...")
        self.worker = ProjectPlanWorker(self.client, request)
        self.worker.planned.connect(self._plan_ready)
        self.worker.failed.connect(self._plan_failed)
        self.worker.finished.connect(lambda: self.plan_button.setEnabled(True))
        self.worker.start()

    def _plan_ready(self, plan: object) -> None:
        if not isinstance(plan, dict):
            self._plan_failed("ULTRON returned an invalid plan.")
            return
        self.plan = plan
        self.project_name.setText(str(plan.get("project_name", "jarvis_project")))
        files = plan.get("files", [])
        lines = [
            f"PROJECT: {plan.get('project_name', '')}",
            f"SUMMARY: {plan.get('summary', '')}",
            f"RUN FILE: {plan.get('run_file', '') or 'See README'}",
            "",
            "FILES TO CREATE:",
        ]
        for item in files:
            content = str(item.get("content", ""))
            lines.append(f"  {item.get('path', '')}  ({len(content.encode('utf-8')):,} bytes)")
        lines.extend([
            "",
            "Nothing has been written yet.",
            "Review this list, then press Approve, Build and ZIP.",
        ])
        self.preview.setPlainText("\n".join(lines))
        self.status.setText(f"Plan ready: {len(files)} files. Waiting for your approval.")
        self.build_button.setEnabled(True)

    def _plan_failed(self, message: str) -> None:
        self.plan = None
        self.build_button.setEnabled(False)
        self.status.setText(f"Plan failed: {message}")
        self.preview.setPlainText(
            "Check the Gemini key/model in Settings, or continue without a key to create a basic starter project."
        )

    def build_project(self) -> None:
        if not self.plan:
            return
        project_name = safe_project_name(
            self.project_name.text(),
            str(self.plan.get("project_name", "jarvis_project")),
        )
        base = Path(self.output_folder.text().strip() or str(PROJECTS_PATH)).expanduser()
        target = base / project_name
        if target.exists():
            target = base / f"{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        zip_path = target.with_suffix(".zip")
        answer = QMessageBox.question(
            self,
            "Approve ULTRON mission",
            f"Create {len(self.plan['files'])} files in:\n{target}\n\nThen create:\n{zip_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("Build cancelled. The plan is still available.")
            return

        try:
            target.mkdir(parents=True, exist_ok=False)
            for item in self.plan["files"]:
                relative = safe_relative_path(str(item["path"]))
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(str(item["content"]), encoding="utf-8")

            run_file = self._ensure_run_launcher(target)
            created_files = [
                path.relative_to(target).as_posix()
                for path in sorted(item for item in target.rglob("*") if item.is_file())
            ]
            manifest = {
                "created_by": APP_NAME,
                "jarvis_version": APP_VERSION,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "request": self.plan.get("request", ""),
                "summary": self.plan.get("summary", ""),
                "run_file": run_file,
                "files": created_files,
            }
            (target / "jarvis_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in sorted(path for path in target.rglob("*") if path.is_file()):
                    archive.write(file_path, file_path.relative_to(target).as_posix())
            self.last_project = target
            self.last_run_file = target / run_file if run_file else None
            self.open_button.setEnabled(True)
            self.run_button.setEnabled(bool(self.last_run_file and self.last_run_file.exists()))
            self.status.setText(f"Mission complete. Project and ZIP created: {zip_path}")
            self.preview.append(f"\nCREATED:\n  {target}\n  {zip_path}")
            QMessageBox.information(self, APP_NAME, f"Project created successfully.\n\n{target}\n\nZIP:\n{zip_path}")
        except Exception as exc:
            self.status.setText(f"Build failed: {exc}")
            QMessageBox.warning(self, APP_NAME, f"Could not build the project:\n{exc}")

    def open_result(self) -> None:
        if self.last_project and self.last_project.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_project)))

    def _ensure_run_launcher(self, target: Path) -> str:
        requested = str(self.plan.get("run_file", "") if self.plan else "").strip()
        run_path: Optional[Path] = None
        if requested:
            candidate = target / safe_relative_path(requested)
            if candidate.exists() and candidate.suffix.lower() not in {".md", ".txt"}:
                run_path = candidate
        if run_path is None:
            preferred = ("main.py", "app.py", "index.html", "run.bat", "start.bat")
            for name in preferred:
                candidate = target / name
                if candidate.exists():
                    run_path = candidate
                    break
        if run_path is None:
            return ""

        relative = run_path.relative_to(target).as_posix()
        if run_path.name.lower() == "run_app.bat":
            return relative
        launcher = target / "RUN_APP.bat"
        suffix = run_path.suffix.lower()
        windows_relative = relative.replace("/", "\\")
        if suffix == ".py":
            command = f'python "{windows_relative}"'
        elif suffix in {".html", ".htm", ".exe"}:
            command = f'start "" "{windows_relative}"'
        elif suffix in {".bat", ".cmd"}:
            command = f'call "{windows_relative}"'
        else:
            return relative
        launcher.write_text(
            "@echo off\n"
            "setlocal EnableExtensions\n"
            "cd /d \"%~dp0\"\n"
            f"{command}\n"
            "if errorlevel 1 (\n"
            "  echo.\n"
            "  echo The generated app stopped with an error.\n"
            "  pause\n"
            ")\n",
            encoding="utf-8",
        )
        return "RUN_APP.bat"

    def run_result(self) -> None:
        if not self.last_run_file or not self.last_run_file.exists():
            return
        answer = QMessageBox.question(
            self,
            "Run generated app",
            "This project was generated by AI. Run it only after reviewing the files.\n\nRun the app now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            suffix = self.last_run_file.suffix.lower()
            if suffix in {".html", ".htm", ".exe"}:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_run_file)))
            elif suffix == ".py":
                subprocess.Popen([sys.executable, str(self.last_run_file)], cwd=str(self.last_project))
            else:
                subprocess.Popen(
                    ["cmd.exe", "/c", str(self.last_run_file)],
                    cwd=str(self.last_project),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not run the generated app:\n{exc}")


class ZipBuilderWidget(QWidget):
    """Builds ZIP files from local folders inside JARVIS."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("ULTRON ZIP BUILDER")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:4px;")
        layout.addWidget(title)

        note = QLabel("Choose a folder, choose where the ZIP should be saved, then build it. Cache files are skipped by default.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#86B9C8;padding:0 4px 8px 4px;")
        layout.addWidget(note)

        form = QGridLayout()
        self.source = QLineEdit()
        self.output = QLineEdit()
        source_button = QPushButton("Browse")
        output_button = QPushButton("Save As")
        source_button.clicked.connect(self.choose_source)
        output_button.clicked.connect(self.choose_output)
        form.addWidget(QLabel("Source folder"), 0, 0)
        form.addWidget(self.source, 0, 1)
        form.addWidget(source_button, 0, 2)
        form.addWidget(QLabel("Output ZIP"), 1, 0)
        form.addWidget(self.output, 1, 1)
        form.addWidget(output_button, 1, 2)
        layout.addLayout(form)

        self.skip_cache = QCheckBox("Skip __pycache__, .pyc, .venv, node_modules and hidden temp folders")
        self.skip_cache.setChecked(True)
        layout.addWidget(self.skip_cache)

        row = QHBoxLayout()
        build = QPushButton("Build ZIP")
        jarvis = QPushButton("Use Current NEXUS Folder")
        build.clicked.connect(self.build_zip)
        jarvis.clicked.connect(self.use_current_jarvis_folder)
        row.addWidget(build)
        row.addWidget(jarvis)
        layout.addLayout(row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(input_style() + "QTextEdit{font-family:Consolas;font-size:11px;padding:10px;}")
        layout.addWidget(self.log, 1)
        self.setStyleSheet(button_style() + input_style() + "QLabel{color:#CFF7FF;} QCheckBox{color:#DDF7FF;padding:6px;}")

    def choose_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder to ZIP", str(Path.home()))
        if not folder:
            return
        self.source.setText(folder)
        if not self.output.text().strip():
            self.output.setText(str(Path(folder).with_suffix(".zip")))

    def choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save ZIP as", str(Path.home() / "jarvis_package.zip"), "ZIP files (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self.output.setText(path)

    def use_current_jarvis_folder(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.source.setText(str(root))
        self.output.setText(str(root.parent / "NEXUS_ULTRON_package.zip"))

    def _should_skip(self, path: Path) -> bool:
        if not self.skip_cache.isChecked():
            return False
        blocked_names = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache"}
        if any(part in blocked_names for part in path.parts):
            return True
        if path.suffix.lower() in {".pyc", ".pyo", ".tmp", ".log"}:
            return True
        return False

    def build_zip(self) -> None:
        source_text = self.source.text().strip()
        output_text = self.output.text().strip()
        if not source_text:
            QMessageBox.warning(self, APP_NAME, "Choose a source folder first.")
            return
        if not output_text:
            QMessageBox.warning(self, APP_NAME, "Choose where the ZIP should be saved first.")
            return
        source = Path(source_text).expanduser()
        output = Path(output_text).expanduser()
        if not source.exists() or not source.is_dir():
            QMessageBox.warning(self, APP_NAME, "Choose a valid source folder first.")
            return
        if not output.name.lower().endswith(".zip"):
            output = output.with_suffix(".zip")
            self.output.setText(str(output))
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            total = 0
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in source.rglob("*"):
                    if not file_path.is_file() or self._should_skip(file_path):
                        continue
                    if file_path.resolve() == output.resolve():
                        continue
                    archive.write(file_path, file_path.relative_to(source).as_posix())
                    count += 1
                    total += file_path.stat().st_size
            self.log.append(f"ZIP created: {output}")
            self.log.append(f"Files: {count}")
            self.log.append(f"Source size: {round(total / 1024, 1)} KB")
            QMessageBox.information(self, APP_NAME, f"ZIP created:\n{output}")
        except Exception as exc:
            self.log.append(f"ERROR: {exc}")
            QMessageBox.warning(self, APP_NAME, f"Could not build ZIP:\n{exc}")


class SelfEditWidget(QWidget):
    """Safe self-editing for JARVIS behavior without arbitrary code changes."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("ULTRON SELF EDIT CENTER")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:4px;")
        layout.addWidget(title)

        note = QLabel("Change ULTRON safely from inside the app. These edits are stored locally and do not rewrite Python code.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#86B9C8;padding:0 4px 8px 4px;")
        layout.addWidget(note)

        config = load_self_edit_config()
        form = QGridLayout()
        self.center_text = QLineEdit(config.get("center_text", "ULTRON"))
        self.voice_style = QComboBox()
        self.voice_style.addItems(["simple", "fast", "teacher", "cool"])
        index = self.voice_style.findText(config.get("voice_style", "simple"))
        self.voice_style.setCurrentIndex(max(0, index))
        form.addWidget(QLabel("Center text"), 0, 0)
        form.addWidget(self.center_text, 0, 1)
        form.addWidget(QLabel("Voice style"), 1, 0)
        form.addWidget(self.voice_style, 1, 1)
        layout.addLayout(form)

        tabs = QTabWidget()
        self.prompt = QTextEdit()
        self.prompt.setPlainText(config.get("custom_prompt", ""))
        self.prompt.setPlaceholderText("Optional. Leave empty to use the built-in ULTRON prompt.")
        self.aliases = QTextEdit()
        self.aliases.setPlainText(config.get("aliases", ""))
        self.aliases.setPlaceholderText("One per line, for example:\nmission => future self\npackage project => zip builder")
        tabs.addTab(self.prompt, "Prompt")
        tabs.addTab(self.aliases, "Command Aliases")
        layout.addWidget(tabs, 1)

        row = QHBoxLayout()
        save = QPushButton("Save Self Edits")
        defaults = QPushButton("Load Safe Defaults")
        save.clicked.connect(self.save)
        defaults.clicked.connect(self.load_defaults)
        row.addWidget(save)
        row.addWidget(defaults)
        layout.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#7FCDE2;padding:4px;")
        layout.addWidget(self.status)
        self.setStyleSheet(button_style() + input_style() + "QLabel{color:#CFF7FF;} QTabWidget::pane{border:1px solid #28758E;} QTabBar::tab{color:#DDF7FF;background:#102A38;padding:8px;}")

    def save(self) -> None:
        data = {
            "center_text": self.center_text.text().strip() or "ULTRON",
            "voice_style": self.voice_style.currentText().strip() or "simple",
            "custom_prompt": self.prompt.toPlainText().strip(),
            "aliases": self.aliases.toPlainText().strip(),
        }
        SELF_EDIT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.setText(f"Saved locally: {SELF_EDIT_PATH}")
        QMessageBox.information(self, APP_NAME, "Self edits saved. Some changes appear immediately; prompt changes apply to the next AI answer.")

    def load_defaults(self) -> None:
        defaults = load_self_edit_config()
        defaults.update({
            "center_text": "ULTRON",
            "voice_style": "simple",
            "custom_prompt": "",
            "aliases": "mission => future self\npackage project => zip builder\nmy map => world map",
        })
        self.center_text.setText(defaults["center_text"])
        self.voice_style.setCurrentText(defaults["voice_style"])
        self.prompt.setPlainText(defaults["custom_prompt"])
        self.aliases.setPlainText(defaults["aliases"])
        self.status.setText("Safe defaults loaded. Press Save Self Edits to keep them.")


class JarvisDashboard(QWidget):
    """Home HUD; existing HoloDesk tools open above it as virtual windows."""
    def __init__(self, canvas: 'HoloCanvas'):
        super().__init__(canvas)
        self.canvas = canvas
        self.setObjectName('jarvisDashboard')
        self.setStyleSheet("""
            QWidget#jarvisDashboard { background: transparent; }
            QFrame#hudPanel { background: rgba(3, 14, 23, 205); border: 1px solid rgba(54, 188, 235, 100); border-radius: 14px; }
            QLabel { color: #CFF7FF; }
            QLabel#hudTitle { color: #72DDF7; font-weight: 800; font-size: 13px; }
            QPushButton { color:#DDF8FF; background:rgba(9,49,72,210); border:1px solid rgba(67,199,238,100); border-radius:8px; padding:7px 10px; }
            QPushButton:hover { background:rgba(17,86,115,235); border-color:rgba(110,226,255,180); }
            QProgressBar { color:#CFF7FF; background:rgba(0,15,24,180); border:1px solid rgba(61,183,220,80); border-radius:5px; text-align:center; }
            QProgressBar::chunk { background:rgba(29,143,200,190); border-radius:4px; }
            QLineEdit { color:#DDF8FF; background:rgba(2,15,24,220); border:1px solid rgba(67,199,238,120); border-radius:8px; padding:8px; }
        """)
        root = QHBoxLayout(self); root.setContentsMargins(18,10,18,16); root.setSpacing(14)

        left = QFrame(); left.setObjectName('hudPanel'); left.setFixedWidth(260)
        left_l = QVBoxLayout(left); left_l.setContentsMargins(14,14,14,14)
        title = QLabel('SYSTEM TELEMETRY'); title.setObjectName('hudTitle'); left_l.addWidget(title)
        self.clock = QLabel('--:--:--'); self.clock.setStyleSheet('font-size:24px;font-weight:700;color:#E6FBFF;'); left_l.addWidget(self.clock)
        self.date = QLabel(''); self.date.setStyleSheet('color:#6FB8C9;'); left_l.addWidget(self.date)
        self.cpu = self._meter('CPU', left_l); self.ram = self._meter('MEMORY', left_l); self.disk = self._meter('DISK', left_l)
        left_l.addSpacing(8); self.net = QLabel('NETWORK  •  ONLINE'); left_l.addWidget(self.net)
        self.ip = QLabel(f'LOCAL IP  •  {local_ip()}'); self.ip.setStyleSheet('color:#6FB8C9;'); left_l.addWidget(self.ip)
        left_l.addStretch()
        for text, cb in [('MISSION BUILDER', canvas.add_mission_builder_window), ('WINDOWS', canvas.add_windows_manager), ('ZIP BUILDER', canvas.add_zip_builder_window), ('SETTINGS', canvas.add_settings_window)]:
            b=QPushButton(text); b.clicked.connect(lambda checked=False, fn=cb: fn()); left_l.addWidget(b)

        right = QFrame(); right.setObjectName('hudPanel'); right.setFixedWidth(310)
        right_l = QVBoxLayout(right); right_l.setContentsMargins(14,14,14,14)
        rt = QLabel('ACTIVITY / COMMAND'); rt.setObjectName('hudTitle'); right_l.addWidget(rt)
        self.activity = QTextEdit(); self.activity.setReadOnly(True); self.activity.setStyleSheet('QTextEdit{color:#85DDF2;background:rgba(0,8,14,180);border:1px solid rgba(60,170,210,60);border-radius:8px;padding:8px;font-family:Consolas;font-size:10px;}')
        self.activity.setHtml('<b>CORE</b> ULTRON reactor initialized.<br><b>VOICE</b> Auto-listen starting…<br><b>WIN32</b> Windows controller ready.'); right_l.addWidget(self.activity, 1)
        self.command = QLineEdit(); self.command.setPlaceholderText('Command: build project / open chrome / calculator / time ...'); self.command.returnPressed.connect(self.run_command); right_l.addWidget(self.command)
        hint=QLabel('VOICE • ALWAYS ON\nSay: Build project • Open Chrome\nOpen Calculator • Time • Notes'); hint.setStyleSheet('color:#78BCCC;'); right_l.addWidget(hint)
        shortcuts = QGridLayout()
        for index, (text, cb) in enumerate([('MISSION', canvas.add_mission_builder_window), ('AIR MENU', canvas.open_air_menu), ('ZIP', canvas.add_zip_builder_window), ('SELF EDIT', canvas.add_self_edit_window)]):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=cb: fn())
            shortcuts.addWidget(button, index // 2, index % 2)
        right_l.addLayout(shortcuts)
        root.addWidget(left); root.addStretch(1); root.addWidget(right)
        self.stats_timer=QTimer(self); self.stats_timer.timeout.connect(self.refresh_stats); self.stats_timer.start(800); self.refresh_stats()

    def _meter(self, name: str, layout: QVBoxLayout) -> QProgressBar:
        label=QLabel(name); label.setStyleSheet('color:#6FB8C9;font-size:10px;'); layout.addWidget(label)
        bar=QProgressBar(); bar.setRange(0,100); bar.setValue(0); bar.setFormat('%p%'); bar.setFixedHeight(18); layout.addWidget(bar); return bar

    def refresh_stats(self) -> None:
        now=datetime.now(); self.clock.setText(now.strftime('%H:%M:%S')); self.date.setText(now.strftime('%A • %d %B %Y'))
        try:
            if PSUTIL_AVAILABLE:
                self.cpu.setValue(int(psutil.cpu_percent(interval=None))); self.ram.setValue(int(psutil.virtual_memory().percent)); self.disk.setValue(int(psutil.disk_usage(str(Path.home().anchor or '/')).percent))
                self.net.setText('NETWORK  •  ONLINE')
            else:
                self.net.setText('NETWORK  •  BASIC MODE')
        except Exception:
            pass

    def log(self, source: str, message: str) -> None:
        stamp=datetime.now().strftime('%H:%M:%S'); self.activity.append(f'<span style="color:#5B9FB2">{stamp}</span> <b>{source}</b> {message}')

    def run_command(self) -> None:
        cmd=self.command.text().strip(); self.command.clear()
        if not cmd: return
        if self.canvas.execute_command(cmd, silent=True):
            self.log('CMD', f'Executed: {cmd}')
        else:
            self.log('ULTRON', self.canvas.ai_client.local_response(cmd))


class HoloCanvas(QWidget):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.setMouseTracking(True)
        self.windows: list[VirtualWindow] = []
        self.active_window: Optional[VirtualWindow] = None
        self.pointer = QPoint(-100, -100)
        self.eye_pointer = QPoint(-100, -100)
        self.gesture_text = "No hand"
        self.hand_detail = ""
        self.show_camera = True
        self.camera_frame: Optional[np.ndarray] = None
        self.camera_pixmap = QPixmap()
        self.phone_frame: Optional[QPixmap] = None

        # Independent rates: Qt UI ≈60 FPS, camera ≈30 FPS, MediaPipe 15–20 FPS.
        self.ui_fps = 0.0
        self.camera_fps = 0.0
        self.tracking_fps = 0.0
        self.frame_counter = 0
        self.fps_started = time.perf_counter()
        self.latest_camera_sequence = -1
        self.latest_tracking_sequence = -1
        self.pointer_target = QPoint(-100, -100)
        self.primary_pinching = False

        self.camera_ok = False
        self.eye_tracking_enabled = settings.eye_tracking
        self.eye_cursor_enabled = settings.eye_cursor
        self.camera_worker: Optional[CameraWorker] = None
        self.tracking_worker: Optional[TrackingWorker] = None

        self.grabbed_window: Optional[VirtualWindow] = None
        self.grab_offset = QPoint()
        self.was_pinching = False
        self.global_cursor_stabilizer = StableRelativeCursor(history_size=6, deadzone=0.0018)
        self.global_mode_was_active = False
        self.global_pinch_frames = 0
        self.global_release_frames = 0
        self.global_click_armed = True
        self.two_hand_resize = False
        self.resize_start_distance = 0.0
        self.resize_start_geometry = QRect()
        self.last_open_event = 0.0
        self.last_gesture_shortcut = 0.0
        self.osk_open_frames = 0
        self.osk_release_frames = 0
        self.osk_gesture_armed = True
        # Air typing / palm backspace (engine lives in gesture_engine.py)
        self.osk_rect: Optional[tuple[int, int, int, int]] = None
        self.osk_open_seen_at = 0.0
        self._osk_checked_at = 0.0
        self.keyboard_typing_active = False
        self.kb_typing_until = 0.0
        self.cursor_hold_until = 0.0
        self._hold_was_active = False
        self.cursor_trail: deque = deque(maxlen=48)      # (time, (x, y)) of the Windows pointer
        self.osk_finger_tapped_this_frame = False
        self.tap_detector = FingerTapDetector(sensitivity=settings.tap_sensitivity)
        self.palm_detector = PalmSwipeDetector(dwell=max(0.0, float(settings.palm_swipe_dwell)))
        self.keyboard_overlay = KeyboardOverlay()
        self.toast_overlay = ToastOverlay()
        self._click_queue: queue.Queue = queue.Queue(maxsize=24)
        self._click_thread: Optional[threading.Thread] = None
        self._osk_wait_since = 0.0
        self._last_hint_at = 0.0
        self._last_click_toast = 0.0

        self.windows_controller = WindowsController()
        self.ai_client = AIClient(settings)
        self.companion_state = CompanionState()
        self.companion_server = CompanionServer(self.companion_state)
        self.command_callbacks: dict[str, Callable[[], Any]] = {}

        self.particles = [
            {"x": random.random(), "y": random.random(), "vx": random.uniform(-0.0004, 0.0004), "vy": random.uniform(0.0001, 0.0007), "r": random.uniform(1.0, 2.7)}
            for _ in range(74)
        ]

        self._start_realtime_pipeline()

        # UI rendering never waits for camera capture, MediaPipe, AI or weather requests.
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.render_timer.timeout.connect(self.render_tick)
        self.render_timer.start(16)
        self.remote_timer = QTimer(self)
        self.remote_timer.timeout.connect(self.poll_remote_events)
        self.remote_timer.start(30)
        self.particle_timer = QTimer(self)
        self.particle_timer.timeout.connect(self.animate_particles)
        self.particle_timer.start(90 if self.settings.performance_mode else 50)

        # Reactor-style home dashboard. Existing tools open above it as floating windows.
        self.dashboard = JarvisDashboard(self)
        self.dashboard.setGeometry(10, 76, max(900, self.width() - 20), max(540, self.height() - 86))
        self.dashboard.show()
        self.dashboard.lower()

    def _start_realtime_pipeline(self) -> None:
        self.camera_worker = CameraWorker(camera_index=0, width=640, height=360, target_fps=30)
        self.tracking_worker = TrackingWorker(
            self.camera_worker,
            performance_mode=lambda: self.settings.performance_mode,
            eye_tracking_enabled=lambda: self.eye_tracking_enabled,
            boost=lambda: self.keyboard_typing_active,
        )
        self.camera_ok = False
        self.camera_fps = 0.0
        self.tracking_fps = 0.0
        self.gesture_text = "Starting"
        self.hand_detail = ""
        self.pointer = QPoint(-100, -100)
        self.pointer_target = QPoint(-100, -100)
        self.camera_worker.start()
        self.tracking_worker.start()

    def set_eye_tracking(self, enabled: bool) -> None:
        self.eye_tracking_enabled = enabled
        self.settings.eye_tracking = enabled
        if not enabled:
            self.eye_pointer = QPoint(-100, -100)
        self.settings.save()

    def set_eye_cursor(self, enabled: bool) -> None:
        self.eye_cursor_enabled = enabled
        self.settings.eye_cursor = enabled
        self.settings.save()

    def set_global_hand_control(self, enabled: bool) -> None:
        self.settings.global_hand_control = enabled
        self.was_pinching = False
        self.global_cursor_stabilizer.reset()
        self.global_mode_was_active = False
        self.global_pinch_frames = 0
        self.global_release_frames = 0
        self.global_click_armed = True
        self.settings.save()

    def set_performance_mode(self, enabled: bool) -> None:
        self.settings.performance_mode = enabled
        self.particle_timer.setInterval(90 if enabled else 50)
        self.settings.save()

    def animate_particles(self) -> None:
        for particle in self.particles:
            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]
            if particle["x"] < 0 or particle["x"] > 1:
                particle["vx"] *= -1
            if particle["y"] > 1:
                particle["y"] = 0
                particle["x"] = random.random()
        # render_tick() owns repaint scheduling at a stable 60 FPS.

    def unregister_window(self, window: VirtualWindow) -> None:
        if window in self.windows:
            self.windows.remove(window)
        if self.active_window is window:
            self.active_window = self.windows[-1] if self.windows else None

    def place_window(self, window: VirtualWindow, geometry: Optional[list[int]] = None) -> VirtualWindow:
        if geometry and len(geometry) == 4:
            window.setGeometry(*map(int, geometry))
        else:
            usable_w = max(1, self.width() - window.width() - 140)
            usable_h = max(1, self.height() - window.height() - 160)
            x = 72 + (len(self.windows) * 42) % usable_w
            y = 102 + (len(self.windows) * 34) % usable_h
            window.move_clamped(x, y)
        self.windows.append(window)
        self.active_window = window
        window.raise_()
        return window

    def add_text_window(self, title: str = "Notes", text: str = "Write something here…", geometry: Optional[list[int]] = None) -> VirtualWindow:
        editor = QTextEdit()
        editor.setPlainText(text)
        editor.setStyleSheet(input_style() + "QTextEdit{border:none;border-radius:0;padding:12px;font-size:14px;}")
        return self.place_window(VirtualWindow(self, title, editor, 420, 290, "text", {"text": text}), geometry)

    def add_image_window(self, path: str = "", geometry: Optional[list[int]] = None) -> Optional[VirtualWindow]:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Choose an image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return None
        view = ImageView(path)
        return self.place_window(VirtualWindow(self, Path(path).name, view, 480, 330, "image", {"path": path}), geometry)

    def add_browser_window(self, url: str = "https://www.google.com", geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Browser", BrowserWidget(url), 720, 490, "browser", {"url": url}), geometry)

    def add_video_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Video Player", MediaWidget("video"), 640, 420, "video"), geometry)

    def add_music_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Music", MediaWidget("music"), 470, 340, "music"), geometry)

    def add_calculator_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Calculator", CalculatorWidget(), 350, 430, "calculator"), geometry)

    def add_calendar_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        calendar = QCalendarWidget()
        calendar.setStyleSheet("QCalendarWidget{background:#08131D;color:#EAFBFF;}QToolButton{color:#EAFBFF;background:#15394A;}")
        return self.place_window(VirtualWindow(self, "Calendar", calendar, 470, 390, "calendar"), geometry)

    def add_weather_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Weather", WeatherWidget(), 430, 320, "weather"), geometry)

    def add_clock_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Clock", ClockWidget(), 410, 250, "clock"), geometry)

    def add_ai_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "ULTRON AI", AIChatWidget(self.ai_client, self), 620, 460, "ai"), geometry)

    def add_world_map_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "ULTRON World Map", WorldMapWidget(), 720, 520, "world_map"), geometry)

    def add_future_self_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Future Self Simulator", FutureSelfWidget(), 680, 500, "future_self"), geometry)

    def add_mission_builder_window(
        self,
        initial_request: str = "",
        geometry: Optional[list[int]] = None,
        auto_start: bool = False,
    ) -> VirtualWindow:
        data = {"request": initial_request} if initial_request else {}
        return self.place_window(
            VirtualWindow(
                self,
                "ULTRON Mission Builder",
                MissionBuilderWidget(self.ai_client, initial_request, auto_start),
                820,
                610,
                "mission_builder",
                data,
            ),
            geometry,
        )

    def add_zip_builder_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "ULTRON ZIP Builder", ZipBuilderWidget(), 720, 500, "zip_builder"), geometry)

    def add_self_edit_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "ULTRON Self Edit Center", SelfEditWidget(), 740, 540, "self_edit"), geometry)

    def add_windows_manager(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Windows Manager", WindowsManagerWidget(self.windows_controller), 760, 500, "windows_manager"), geometry)

    def add_voice_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Voice Commands", VoiceControlWidget(self), 520, 350, "voice"), geometry)

    def add_phone_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        return self.place_window(VirtualWindow(self, "Phone Companion", PhoneCompanionWidget(self), 530, 490, "phone"), geometry)

    def add_settings_window(self, geometry: Optional[list[int]] = None) -> VirtualWindow:
        widget = SettingsWidget(self.settings)
        widget.settings_changed.connect(self.reload_ai_client)
        widget.auth_session_changed.connect(self.set_supabase_session)
        widget.authenticated.connect(self._on_supabase_authenticated)
        return self.place_window(VirtualWindow(self, "Settings", widget, 540, 390, "settings"), geometry)

    def reload_ai_client(self) -> None:
        self.ai_client = AIClient(self.settings)

    def set_supabase_session(self, session: Optional[dict[str, Any]]) -> None:
        self.ai_client.set_session(session)

    def _on_supabase_authenticated(self, session: dict[str, Any]) -> None:
        self.ai_client.set_session(session)
        self.ai_client._sync_profile()

    def open_air_menu(self) -> None:
        now = time.monotonic()
        if now - self.last_open_event < 1.25:
            return
        self.last_open_event = now
        menu = QFrame(self)
        menu.setObjectName("airMenu")
        menu.setGeometry(24, 88, 270, 540)
        menu.setStyleSheet("""
            QFrame#airMenu{background:rgba(6,18,28,248);border:1px solid rgba(88,225,255,190);border-radius:20px;}
            QLabel{color:#8BE9FF;font-weight:800;} QPushButton{color:#EAFBFF;background:rgba(31,74,94,205);border:1px solid rgba(90,220,255,65);border-radius:9px;padding:8px;text-align:left;}
            QPushButton:hover{background:rgba(65,126,150,235);}
        """)
        layout = QVBoxLayout(menu)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("ULTRON AIR MENU")
        layout.addWidget(title)
        items = [
            ("MISSION BUILDER", self.add_mission_builder_window),
            ("🛠 Self Edit Center", self.add_self_edit_window),
            ("🧭 World Map", self.add_world_map_window),
            ("🔮 Future Self", self.add_future_self_window),
            ("📦 ZIP Builder", self.add_zip_builder_window),
            ("🪟 Windows Manager", self.add_windows_manager),
            ("🤖 AI Assistant", self.add_ai_window),
            ("🌐 Browser", self.add_browser_window),
            ("📝 Notes", self.add_text_window),
            ("🎬 Video", self.add_video_window),
            ("♫ Music", self.add_music_window),
            ("🧮 Calculator", self.add_calculator_window),
            ("📅 Calendar", self.add_calendar_window),
            ("🌦 Weather", self.add_weather_window),
            ("🕒 Clock", self.add_clock_window),
            ("🎙 Voice", self.add_voice_window),
            ("📱 Phone Companion", self.add_phone_window),
            ("⚙ Settings", self.add_settings_window),
        ]
        for text, callback in items:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, cb=callback: (cb(), menu.deleteLater()))
            layout.addWidget(button)
        close = QPushButton("× Close Menu")
        close.clicked.connect(menu.deleteLater)
        layout.addWidget(close)
        menu.show()
        menu.raise_()

    def window_at(self, x: int, y: int) -> Optional[VirtualWindow]:
        for window in reversed(self.windows):
            if window.isVisible() and window.geometry().contains(x, y):
                return window
        return None

    def _point_from_hand(self, hand: dict[str, Any]) -> QPoint:
        ix, iy = hand["index"][0], hand["index"][1]
        return QPoint(
            int(clamp(ix * self.width(), 0, self.width() - 1)),
            int(clamp(iy * self.height(), 0, self.height() - 1)),
        )

    def _global_hand_mode_active(self) -> bool:
        host = self.window()
        return bool(
            self.settings.global_hand_control
            and self.windows_controller.available
            and (not host.isVisible() or host.isMinimized())
        )

    def _kb_region(self) -> tuple[float, float, float, float]:
        """Part of the camera view that represents the on-screen keyboard (see settings.json kb_map_*)."""
        cfg = self.settings
        x0, x1 = sorted((clamp(float(cfg.kb_map_x0), 0.0, 0.9), clamp(float(cfg.kb_map_x1), 0.1, 1.0)))
        y0, y1 = sorted((clamp(float(cfg.kb_map_y0), 0.0, 0.9), clamp(float(cfg.kb_map_y1), 0.1, 1.0)))
        if x1 - x0 < 0.2:
            x0, x1 = 0.06, 0.94
        if y1 - y0 < 0.2:
            y0, y1 = 0.18, 0.80
        return x0, x1, y0, y1

    def set_tap_sensitivity(self, value: float) -> None:
        value = clamp(float(value), 0.5, 4.0)
        self.settings.tap_sensitivity = value
        self.tap_detector.set_sensitivity(value)
        self.settings.save()

    def open_windows_keyboard(self, hands: Optional[list[dict[str, Any]]] = None) -> bool:
        center_x = 0.5
        center_y = 0.5
        if hands and len(hands) >= 2:
            palms = [hand.get("palm", hand.get("index", (0.5, 0.5, 0.0))) for hand in hands[:2]]
            center_x = sum(float(point[0]) for point in palms) / len(palms)
            center_y = sum(float(point[1]) for point in palms) / len(palms)
        if self.windows_controller.onscreen_keyboard_rect() is not None:
            self.kb_typing_until = time.monotonic() + 1.5       # already open: just start air typing
            return True
        opened = self.windows_controller.launch("osk.exe")
        air_log(f"launch osk.exe -> {opened}")
        if opened:
            self._osk_wait_since = time.monotonic()
            if hands:
                QTimer.singleShot(50, self.window().hide)
            QTimer.singleShot(500, lambda: self.windows_controller.position_onscreen_keyboard(center_x, center_y))
            QTimer.singleShot(1200, lambda: self.windows_controller.position_onscreen_keyboard(center_x, center_y))
            self.gesture_text = "WINDOWS KEYBOARD"
            self.hand_detail = "Native On-Screen Keyboard opened"
        return opened

    def _refresh_osk_state(self, now: float) -> None:
        if now - self._osk_checked_at < 0.20:
            return
        self._osk_checked_at = now
        rect = self.windows_controller.onscreen_keyboard_rect()
        if rect is not None and (rect[2] - rect[0] < 200 or rect[3] - rect[1] < 80):
            rect = None
        previous = self.osk_rect
        self.osk_rect = rect
        if rect is not None and previous is None:
            self.osk_open_seen_at = now
            air_log(f"OSK detected rect={rect}")
        if rect is None and self._osk_wait_since and now - self._osk_wait_since > 3.0:
            self._osk_wait_since = 0.0
            air_log("OSK was launched but its window was not found")
            self.toast_overlay.show_text("Keyboard window not detected - open osk.exe manually", 3.0)

    def _update_windows_keyboard_gesture(self, hands: list[dict[str, Any]], now: float) -> bool:
        """Both palms open for ~0.4 s: opens the keyboard (only when it is not open yet)."""
        two_open = len(hands) >= 2 and all(bool(hand.get("palm_open")) for hand in hands[:2])
        if two_open:
            self.osk_open_frames += 1
            self.osk_release_frames = 0
            if self.osk_gesture_armed and self.osk_open_frames >= 8:
                self.osk_gesture_armed = False
                if self.osk_rect is None:
                    self.open_windows_keyboard(hands)
                else:
                    self.kb_typing_until = max(self.kb_typing_until, now + 0.9)
        else:
            self.osk_open_frames = 0
            self.osk_release_frames += 1
            if self.osk_release_frames >= 6:
                self.osk_gesture_armed = True
        return two_open

    def _leave_typing_mode(self, toast: bool = True) -> None:
        if not self.keyboard_typing_active:
            return
        self.keyboard_typing_active = False
        self.keyboard_overlay.clear()
        self.tap_detector.reset()
        self.global_cursor_stabilizer.reset()
        self.global_pinch_frames = 0
        self.global_release_frames = 0
        self.global_click_armed = True
        if toast:
            self.toast_overlay.show_text("CURSOR MODE", 0.9)

    def _click_worker(self) -> None:
        """Presses keys on a background thread so hover delays never stall the UI / tracking."""
        while True:
            item = self._click_queue.get()
            if item is None:
                return
            px, py, finger = item
            try:
                ok = self.windows_controller.click_screen_point(int(px), int(py))
                reason = "" if ok else getattr(self.windows_controller, "last_click_error", "") or "click failed"
            except Exception as exc:          # never let the worker die
                ok, reason = False, f"exception: {exc}"
            air_log(f"TAP {finger} -> ({int(px)},{int(py)}) {'OK' if ok else 'FAILED: ' + reason}")
            if not ok and time.monotonic() - self._last_click_toast > 4.0:
                self._last_click_toast = time.monotonic()
                QTimer.singleShot(0, lambda r=reason: self.toast_overlay.show_text("KEY PRESS FAILED: " + r[:46], 2.5))

    def _queue_key_press(self, px: float, py: float, finger: str) -> None:
        if self._click_thread is None or not self._click_thread.is_alive():
            self._click_thread = threading.Thread(target=self._click_worker, name="AirTypingClicks", daemon=True)
            self._click_thread.start()
        try:
            self._click_queue.put_nowait((px, py, finger))
        except queue.Full:
            pass

    def _update_keyboard_typing(self, hands: list[dict[str, Any]], now: float) -> bool:
        """Air typing: while the On-Screen Keyboard is open and two hands are in view, every finger
        of both hands can press keys. Returns True while typing mode owns the hands."""
        self.osk_finger_tapped_this_frame = False
        if self.osk_rect is None:
            self.kb_typing_until = 0.0
            self._leave_typing_mode(toast=False)
            return False
        self._osk_wait_since = 0.0
        if len(hands) >= 2:
            self.kb_typing_until = now + 1.5                 # survives a hand being lost for a moment
        if now >= self.kb_typing_until:
            self._leave_typing_mode()
            if len(hands) < 2 and now - self._last_hint_at > 8.0 and self.osk_open_seen_at and now - self.osk_open_seen_at < 20.0:
                self._last_hint_at = now
                self.toast_overlay.show_text("Show BOTH hands to start air typing", 1.8)
            return False
        if not self.keyboard_typing_active:
            self.keyboard_typing_active = True
            self.tap_detector.reset()
            self.global_cursor_stabilizer.reset()
            self.global_pinch_frames = 0
            self.global_release_frames = 0
            self.global_click_armed = True
            self.was_pinching = False
            self.primary_pinching = False
            air_log(f"AIR TYPING started, OSK rect={self.osk_rect}")
            self.toast_overlay.show_text("AIR TYPING • tap with any finger", 1.6)

        region = self._kb_region()
        pressed: list[str] = []
        for event in sorted(self.tap_detector.update(hands, now), key=lambda e: -e.strength)[:3]:
            px, py = map_camera_to_rect(event.x, event.y, self.osk_rect, region)
            self._queue_key_press(px, py, event.finger)
            self.keyboard_overlay.flash(px, py)
            pressed.append(event.finger)

        dots: list[tuple[float, float, int, str, float]] = []
        meters = self.tap_detector.meters
        for hand_index, hand in enumerate(hands[:2]):
            points = hand.get("points", [])
            hand_meter = meters[hand_index] if hand_index < len(meters) else {}
            for name, point_index in FINGER_TIP.items():
                if len(points) > point_index:
                    px, py = map_camera_to_rect(points[point_index][0], points[point_index][1], self.osk_rect, region)
                    dots.append((px, py, hand_index, name, float(hand_meter.get(name, 0.0))))
        self.keyboard_overlay.set_state(self.osk_rect, dots)

        self.gesture_text = "AIR TYPING"
        if pressed:
            self.osk_finger_tapped_this_frame = True
            self.hand_detail = "Pressed with " + ", ".join(pressed)
        else:
            self.hand_detail = "Tap a finger • lower one hand for the cursor"
        return True

    def _restore_pointer_before_swipe(self, start_t: float) -> None:
        """The rising palm also dragged the pointer upward; put it back where it was when the swipe began."""
        target = None
        for stamp, pos in self.cursor_trail:
            if stamp <= start_t:
                target = pos
            else:
                break
        if target is None and self.cursor_trail:
            target = self.cursor_trail[0][1]
        if target is not None:
            self.windows_controller.set_cursor_pixels(*target)
            self.cursor_trail.clear()

    def _typing_pointer_hand(self, hands: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """While air typing, only a hand that is clearly POINTING (index up, other three fingers curled)
        or pinching drives the mouse; typing hands never push the pointer around."""
        for hand in hands:
            fingers = hand.get("fingers", {})
            if hand.get("gesture") == "pinch" or (
                fingers.get("index") and not (fingers.get("middle") or fingers.get("ring") or fingers.get("pinky"))
            ):
                return hand
        return None

    def _update_palm_swipe(self, hands: list[dict[str, Any]], now: float, suppress: bool = False) -> bool:
        """Open palm moves upward -> one Backspace (deletes the selection or the last character)."""
        rise = 0.22 if self.keyboard_typing_active else None   # stricter while typing: hands move a lot
        event = self.palm_detector.update(hands, now, rise=rise)
        if event is None or suppress:
            return False
        if not self.windows_controller.press_backspace():
            return False
        self._restore_pointer_before_swipe(event.start_t)
        self.cursor_hold_until = now + 0.30        # swallow the last part of the upward hand movement
        air_log(f"PALM SWIPE -> Backspace (rise {event.rise:.2f}, speed {event.speed:.2f}/s)")
        self.global_cursor_stabilizer.reset()
        self.gesture_text = "PALM BACKSPACE"
        self.hand_detail = "Deleted selected text or last character"
        self.toast_overlay.show_text("\u232b  BACKSPACE", 0.9)
        return True

    def _update_global_hand_control(self, hands: list[dict[str, Any]]) -> None:
        primary = hands[0]
        if time.monotonic() < self.cursor_hold_until:
            # Keep tracking the hand (so there is no jump afterwards) but do not move the pointer yet.
            self.global_cursor_stabilizer.update((primary["index"][0], primary["index"][1]), float(primary.get("confidence", 0.0)))
            self.gesture_text = "PALM BACKSPACE"
            self.hand_detail = "Pointer stays where it was"
            self._hold_was_active = True
            return
        if self._hold_was_active:
            self._hold_was_active = False
            self.global_cursor_stabilizer.reset()      # drop any smoothed leftover motion from the swipe
        self.gesture_text = f"GLOBAL {primary['gesture']}"
        self.hand_detail = "Windows cursor control active"
        # Use a forgiving, frame-confirmed pinch detector for Windows clicks.
        # This works better with webcams that leave a small visual gap between
        # the tracked thumb and index fingertips.
        pinch_distance = float(primary.get("pinch_distance", 1.0))
        pinch_ratio = float(primary.get("pinch_ratio", 99.0))
        pinch_candidate = pinch_ratio <= 0.55 or pinch_distance <= 0.105
        release_candidate = pinch_ratio >= 0.85 and pinch_distance >= 0.115
        if pinch_candidate:
            self.global_pinch_frames += 1
            self.global_release_frames = 0
        elif release_candidate:
            self.global_release_frames += 1
            self.global_pinch_frames = 0

        if self.global_release_frames >= 2:
            self.global_click_armed = True

        pinching = self.global_pinch_frames >= 2
        self.primary_pinching = pinching

        ix, iy = primary["index"][0], primary["index"][1]
        confidence = float(primary.get("confidence", 0.0))
        relative_motion = self.global_cursor_stabilizer.update((ix, iy), confidence)

        # Lock the pointer to its last stable target while the fingers close.
        # Otherwise the index fingertip movement can pull it off the file just
        # before Windows receives the click.
        freeze_cursor = pinch_candidate or (
            not self.global_click_armed and self.global_release_frames < 2
        )
        if not freeze_cursor and relative_motion is not None:
            self.windows_controller.move_cursor_relative(*relative_motion)

        if pinching and self.global_click_armed and not self.osk_finger_tapped_this_frame:
            if self.windows_controller.cursor_over_onscreen_keyboard():
                self.windows_controller.click()
            else:
                # A single deliberate pinch opens desktop files immediately.
                self.windows_controller.double_click()
            self.global_click_armed = False
        self.was_pinching = pinching

    def update_hand_control(self, hands: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        pointer_now = self.windows_controller.get_cursor_pos()
        if pointer_now is not None:
            self.cursor_trail.append((now, pointer_now))
        self._refresh_osk_state(now)
        keyboard_pose = self._update_windows_keyboard_gesture(hands, now)
        typing = self._update_keyboard_typing(hands, now)
        swiped = self._update_palm_swipe(hands, now, suppress=keyboard_pose and self.osk_rect is None)
        locked = keyboard_pose or typing
        if swiped:
            self.primary_pinching = False
            self.was_pinching = False
            return
        if not hands:
            if self._global_hand_mode_active():
                if not self.global_mode_was_active:
                    self.global_cursor_stabilizer.reset()
                    self.global_mode_was_active = True
                reset_after_loss = self.global_cursor_stabilizer.mark_missing()
                self.gesture_text = "GLOBAL WAITING"
                self.hand_detail = "Cursor held at last stable position"
                if reset_after_loss:
                    self.primary_pinching = False
                    self.was_pinching = False
                    self.global_pinch_frames = 0
                    self.global_release_frames = 0
                    self.global_click_armed = True
                return
            self.global_mode_was_active = False
            self.gesture_text = "No hand"
            self.hand_detail = ""
            self.pointer_target = QPoint(-100, -100)
            self.primary_pinching = False
            self.was_pinching = False
            self.grabbed_window = None
            self.two_hand_resize = False
            self.global_cursor_stabilizer.reset()
            self.global_pinch_frames = 0
            self.global_release_frames = 0
            self.global_click_armed = True
            return

        if self._global_hand_mode_active():
            if not self.global_mode_was_active:
                self.global_cursor_stabilizer.reset()
                self.global_mode_was_active = True
                self.global_pinch_frames = 0
                self.global_release_frames = 0
                self.global_click_armed = True
            self.grabbed_window = None
            self.two_hand_resize = False
            if typing:
                pointer = self._typing_pointer_hand(hands)
                if pointer is not None:
                    self._update_global_hand_control([pointer])
                    return
            if locked:
                self.global_cursor_stabilizer.reset()
                self.primary_pinching = False
                self.was_pinching = False
                self.global_pinch_frames = 0
                self.global_release_frames = 0
                self.global_click_armed = True
                if not typing:
                    self.gesture_text = "WINDOWS KEYBOARD • CURSOR LOCKED"
                    self.hand_detail = "Lower one hand to resume cursor control"
                return
            self._update_global_hand_control(hands)
            return

        if self.global_mode_was_active:
            self.global_cursor_stabilizer.reset()
            self.global_mode_was_active = False
        if locked:
            self.primary_pinching = False
            self.was_pinching = False
            self.grabbed_window = None
            self.two_hand_resize = False
            if not typing:
                self.gesture_text = "WINDOWS KEYBOARD • CURSOR LOCKED"
                self.hand_detail = "Lower one hand to resume cursor control"
            return
        primary = hands[0]
        self.pointer_target = self._point_from_hand(primary)
        self.gesture_text = primary["gesture"]
        finger_letters = "".join(name[0].upper() for name, state in primary["fingers"].items() if state)
        self.hand_detail = f"{primary['handedness']} • fingers:{finger_letters or 'none'} • pinch:{primary['pinch_strength']:.0%}"

        if primary["palm_open"] and time.monotonic() - self.last_open_event > 1.0:
            self.open_air_menu()

        pinching = bool(primary["pinching"])
        self.primary_pinching = pinching
        x, y = self.pointer_target.x(), self.pointer_target.y()

        if pinching and not self.was_pinching:
            target_widget = self.childAt(x, y)
            if isinstance(target_widget, QPushButton):
                target_widget.click()
                self.was_pinching = True
                return
            target = self.window_at(x, y)
            if target:
                self.grabbed_window = target
                self.active_window = target
                target.raise_()
                self.grab_offset = QPoint(x - target.x(), y - target.y())

        two_pinches = len(hands) >= 2 and hands[0]["pinching"] and hands[1]["pinching"]
        if two_pinches and self.grabbed_window:
            p1 = self._point_from_hand(hands[0])
            p2 = self._point_from_hand(hands[1])
            current_distance = math.hypot(p1.x() - p2.x(), p1.y() - p2.y())
            if not self.two_hand_resize:
                self.two_hand_resize = True
                self.resize_start_distance = max(20.0, current_distance)
                self.resize_start_geometry = self.grabbed_window.geometry()
            scale = clamp(current_distance / self.resize_start_distance, 0.55, 2.2)
            new_w = int(clamp(self.resize_start_geometry.width() * scale, 250, self.width() - 16))
            new_h = int(clamp(self.resize_start_geometry.height() * scale, 150, self.height() - 86))
            center_x = (p1.x() + p2.x()) // 2
            center_y = (p1.y() + p2.y()) // 2
            self.grabbed_window.resize(new_w, new_h)
            self.grabbed_window.move_clamped(center_x - new_w // 2, center_y - new_h // 2)
        elif pinching and self.grabbed_window:
            self.two_hand_resize = False
        else:
            self.two_hand_resize = False

        if not pinching:
            self.grabbed_window = None

        gesture_now = time.monotonic()
        if len(hands) >= 2 and gesture_now - self.last_gesture_shortcut > 1.5:
            gestures = {hands[0]["gesture"], hands[1]["gesture"]}
            if gestures == {"open", "fist"} and self.active_window:
                self.active_window.toggle_maximize()
                self.last_gesture_shortcut = gesture_now
            elif hands[0]["gesture"] == "victory" and hands[1]["gesture"] == "victory":
                self.save_workspace(show_message=False)
                self.last_gesture_shortcut = gesture_now

        self.was_pinching = pinching

    def update_eye_control(self, face: Optional[dict[str, Any]]) -> None:
        if not face:
            self.eye_pointer = QPoint(-100, -100)
            return
        gx, gy = face["gaze"]
        self.eye_pointer = QPoint(int(gx * self.width()), int(gy * self.height()))
        if self.eye_cursor_enabled and self.pointer_target.x() < 0:
            self.pointer_target = QPoint(self.eye_pointer.x(), self.eye_pointer.y())

    def _refresh_camera_pixmap(self, frame: np.ndarray) -> None:
        if not self.show_camera:
            return
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, _ = rgb.shape
            image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            source = QPixmap.fromImage(image)
            target_size = QSize(max(1, self.width()), max(1, self.height() - 70))
            transform = Qt.TransformationMode.FastTransformation if self.settings.performance_mode else Qt.TransformationMode.SmoothTransformation
            self.camera_pixmap = source.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                transform,
            )
        except Exception:
            self.camera_pixmap = QPixmap()

    def _interpolate_pointer(self) -> None:
        if self.pointer_target.x() < 0:
            self.pointer = QPoint(-100, -100)
            return
        if self.pointer.x() < 0:
            self.pointer = QPoint(self.pointer_target.x(), self.pointer_target.y())
            return

        alpha = 0.28
        nx = self.pointer.x() + (self.pointer_target.x() - self.pointer.x()) * alpha
        ny = self.pointer.y() + (self.pointer_target.y() - self.pointer.y()) * alpha
        if abs(self.pointer_target.x() - nx) < 0.8:
            nx = self.pointer_target.x()
        if abs(self.pointer_target.y() - ny) < 0.8:
            ny = self.pointer_target.y()
        self.pointer = QPoint(int(nx), int(ny))

    def render_tick(self) -> None:
        # Pull the newest camera frame without blocking. Old frames are discarded.
        if self.camera_worker is not None:
            frame, sequence, camera_fps, camera_status, opened = self.camera_worker.snapshot()
            self.camera_ok = opened
            self.camera_fps = camera_fps
            if frame is not None and sequence != self.latest_camera_sequence:
                self.latest_camera_sequence = sequence
                self.camera_frame = frame
                self._refresh_camera_pixmap(frame)
            if not opened and frame is None:
                self.gesture_text = camera_status

        # Gesture actions update only when MediaPipe publishes a new result.
        if self.tracking_worker is not None:
            hands, face, sequence, tracking_fps, tracking_status = self.tracking_worker.snapshot()
            self.tracking_fps = tracking_fps
            if sequence != self.latest_tracking_sequence:
                self.latest_tracking_sequence = sequence
                self.update_hand_control(hands)
                if self.eye_tracking_enabled:
                    self.update_eye_control(face)
            elif sequence == 0 and tracking_status != "Hand tracking active":
                self.gesture_text = tracking_status

        # Visible cursor and grabbed windows stay smooth at the UI rate.
        self._interpolate_pointer()
        if self.primary_pinching and self.grabbed_window and not self.two_hand_resize and self.pointer.x() >= 0:
            self.grabbed_window.move_clamped(
                self.pointer.x() - self.grab_offset.x(),
                self.pointer.y() - self.grab_offset.y(),
            )

        self.update()

    def poll_remote_events(self) -> None:
        for _ in range(20):
            try:
                event = self.companion_state.events.get_nowait()
            except queue.Empty:
                break
            event_type = event.get("type")
            if event_type == "move":
                dx = safe_int(event.get("dx"))
                dy = safe_int(event.get("dy"))
                if self.windows_controller.available:
                    self.windows_controller.move_cursor(dx, dy)
                else:
                    base_x = self.pointer.x() if self.pointer.x() >= 0 else self.width() // 2
                    base_y = self.pointer.y() if self.pointer.y() >= 0 else self.height() // 2
                    self.pointer_target = QPoint(
                        int(clamp(base_x + dx, 0, self.width() - 1)),
                        int(clamp(base_y + dy, 0, self.height() - 1)),
                    )
            elif event_type == "command":
                command = str(event.get("command", ""))
                if command == "click":
                    if self.windows_controller.available:
                        self.windows_controller.click()
                    else:
                        target = self.childAt(self.pointer)
                        if isinstance(target, QPushButton):
                            target.click()
                else:
                    self.execute_command(command, silent=True)

    def start_companion(self) -> tuple[bool, str]:
        return self.companion_server.start(self.settings.phone_port)

    def stop_companion(self) -> None:
        self.companion_server.stop()

    def execute_command(self, raw_command: str, silent: bool = False) -> bool:
        command = raw_command.strip().lower()
        normalized = command.replace("-", " ").replace("_", " ")
        command_words = set(normalized.split())

        def has(*phrases: str) -> bool:
            return contains_phrase(normalized, *phrases)

        def log(source: str, message: str) -> None:
            reactor = getattr(self, "reactor_console", None)
            if reactor is not None and hasattr(reactor, "log"):
                reactor.log(source, message)

        aliased = self._custom_alias_command(normalized)
        if aliased and aliased != normalized:
            return self.execute_command(aliased, silent=silent)

        if has("clear memory", "forget conversation", "forget our conversation"):
            self.ai_client.clear_memory()
            log("ULTRON", "Conversation memory cleared.")
            return True

        if has("help", "commands", "what can you do"):
            log("ULTRON", "Commands: build project, zip builder, self edit, open Chrome, open Notepad, open Calculator, time.")
            return True
        if has("what is your name", "who are you"):
            log("ULTRON", "I am ULTRON, your local Windows assistant.")
            return True
        if "time" in command_words or has("what time"):
            log("TIME", f"Current time: {datetime.now().strftime('%H:%M:%S')}")
            return True
        if has("open chrome"):
            return self.windows_controller.launch("chrome")
        if has("open notepad", "notepad"):
            return self.windows_controller.launch("notepad")
        if has("open calculator", "open calc", "calc.exe", "windows calculator", "calculator"):
            return self.windows_controller.launch("calc")
        if has("open windows browser", "windows browser", "open default browser", "default browser"):
            return QDesktopServices.openUrl(QUrl("https://www.google.com"))
        if has("open browser", "open brauzer", "open brouser", "open bowser", "browser", "brauzer", "brouser"):
            self.add_browser_window(); return True
        if has("open ai", "ai assistant"):
            self.add_ai_window(); return True
        if has("world map", "digital twin", "my world"):
            self.add_world_map_window(); return True
        if has("future self", "future simulator", "simulate future"):
            self.add_future_self_window(); return True
        mission_phrases = (
            "mission builder", "build project", "create project", "make project",
            "generate a random app", "generate random app", "make a random app", "make random app",
            "create a random app", "create random app",
            "generate an app", "generate app", "build an app", "build app",
            "create an app", "create app",
        )
        if has(*mission_phrases) or project_generation_intent(normalized):
            lower_raw = raw_command.lower()
            request = ""
            for phrase in mission_phrases:
                position = lower_raw.find(phrase)
                if position >= 0:
                    request = raw_command[position + len(phrase):].strip(" :-,.")
                    break
            if not request and not any(phrase in lower_raw for phrase in mission_phrases):
                request = raw_command.strip()
            random_request = random_app_intent(normalized) or has(
                "generate a random app", "generate random app", "make a random app", "make random app",
                "create a random app", "create random app",
            )
            if random_request:
                request = (
                    "Create one small, original and useful random desktop app. Choose the idea yourself. "
                    "Make it complete, runnable on Windows, visually clear, and include a README with exact run instructions."
                )
            self.add_mission_builder_window(request, auto_start=bool(request)); return True
        if has("zip builder", "make zip", "build zip", "create zip", "package files"):
            self.add_zip_builder_window(); return True
        if has("self edit", "self editor", "edit yourself", "change yourself"):
            self.add_self_edit_window(); return True
        if has("windows manager", "window manager"):
            self.add_windows_manager(); return True
        if has("notes", "note"):
            self.add_text_window(); return True
        if has("calculator widget"):
            self.add_calculator_window(); return True
        if has("calendar"):
            self.add_calendar_window(); return True
        if has("weather"):
            self.add_weather_window(); return True
        if has("clock"):
            self.add_clock_window(); return True
        if has("video"):
            self.add_video_window(); return True
        if has("music"):
            self.add_music_window(); return True
        if has("phone"):
            self.add_phone_window(); return True
        if has("open keyboard", "show keyboard", "on screen keyboard", "osk"):
            return self.open_windows_keyboard()
        if has("air menu", "air_menu"):
            self.open_air_menu(); return True
        if has("close window", "close_window"):
            if self.active_window:
                self.active_window.close(); return True
            return False
        if has("maximize"):
            if self.active_window:
                self.active_window.maximize_window(); return True
            return False
        if has("minimize"):
            if self.active_window:
                self.active_window.minimize_window(); return True
            return False
        if has("restore"):
            if self.active_window:
                self.active_window.restore_window(); return True
            return False
        if has("snap left"):
            if self.active_window:
                self.active_window.snap_left(); return True
            return False
        if has("snap right"):
            if self.active_window:
                self.active_window.snap_right(); return True
            return False
        if has("rotate"):
            if self.active_window:
                self.active_window.rotate_by(15); return True
            return False
        if has("camera off", "disable camera"):
            self.show_camera = False; self.settings.show_camera = False; self.settings.save(); return True
        if has("camera on", "enable camera"):
            self.show_camera = True; self.settings.show_camera = True; self.settings.save(); return True
        if has("save workspace", "save_workspace"):
            self.save_workspace(show_message=not silent); return True
        if has("load workspace"):
            self.load_workspace(); return True
        if has("next monitor", "next_monitor"):
            self.window().move_to_next_monitor(); return True
        return False

    def _custom_alias_command(self, normalized: str) -> str:
        aliases = load_self_edit_config().get("aliases", "")
        for line in aliases.splitlines():
            if "=>" not in line:
                continue
            phrase, target = [part.strip().lower() for part in line.split("=>", 1)]
            if phrase and target and phrase in normalized:
                return target
        return ""

    def screen_context(self) -> str:
        active = self.active_window.title() if self.active_window else "None"
        titles = ", ".join(window.title() for window in self.windows[-12:]) or "None"
        system_windows = self.windows_controller.list_windows()[:10]
        real_titles = ", ".join(row["title"] for row in system_windows) if system_windows else "Unavailable"
        return (
            f"HoloDesk active window: {active}\n"
            f"HoloDesk open widgets: {titles}\n"
            f"Real Windows applications: {real_titles}\n"
            f"Hand gesture: {self.gesture_text}\n"
            f"Camera: {'on' if self.camera_ok else 'unavailable'}\n"
            f"Eye tracking: {'on' if self.eye_tracking_enabled else 'off'}"
        )

    def save_workspace(self, show_message: bool = True) -> None:
        payload = {
            "version": APP_VERSION,
            "saved_at": datetime.now().isoformat(),
            "windows": [window.serialize() for window in self.windows if window.isVisible()],
        }
        WORKSPACE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if show_message:
            QMessageBox.information(self, APP_NAME, f"Workspace saved:\n{WORKSPACE_PATH}")

    def load_workspace(self) -> None:
        if not WORKSPACE_PATH.exists():
            QMessageBox.information(self, APP_NAME, "No saved workspace found.")
            return
        try:
            payload = json.loads(WORKSPACE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not read workspace: {exc}")
            return
        for window in list(self.windows):
            window.close()
        for item in payload.get("windows", []):
            self.restore_item(item)

    def restore_item(self, item: dict[str, Any]) -> None:
        kind = item.get("type", "text")
        data = item.get("data", {})
        geometry = item.get("geometry")
        window: Optional[VirtualWindow] = None
        if kind in {"text", "notes"}:
            window = self.add_text_window(item.get("title", "Notes"), data.get("text", ""), geometry)
        elif kind == "image" and Path(data.get("path", "")).exists():
            window = self.add_image_window(data.get("path", ""), geometry)
        elif kind == "browser":
            window = self.add_browser_window(data.get("url", "https://www.google.com"), geometry)
        elif kind == "video": window = self.add_video_window(geometry)
        elif kind == "music": window = self.add_music_window(geometry)
        elif kind == "calculator": window = self.add_calculator_window(geometry)
        elif kind == "calendar": window = self.add_calendar_window(geometry)
        elif kind == "weather": window = self.add_weather_window(geometry)
        elif kind == "clock": window = self.add_clock_window(geometry)
        elif kind == "ai": window = self.add_ai_window(geometry)
        elif kind == "world_map": window = self.add_world_map_window(geometry)
        elif kind == "future_self": window = self.add_future_self_window(geometry)
        elif kind == "mission_builder": window = self.add_mission_builder_window(data.get("request", ""), geometry)
        elif kind == "zip_builder": window = self.add_zip_builder_window(geometry)
        elif kind == "self_edit": window = self.add_self_edit_window(geometry)
        elif kind == "windows_manager": window = self.add_windows_manager(geometry)
        elif kind == "voice": window = self.add_voice_window(geometry)
        elif kind == "phone": window = self.add_phone_window(geometry)
        elif kind == "settings": window = self.add_settings_window(geometry)
        elif kind == "control_center":
            window = self.place_window(VirtualWindow(self, "ULTRON Control Center", ControlCenter(self), 650, 500, "control_center"), geometry)
        if window:
            rotation = safe_int(item.get("rotation"))
            if rotation:
                window.rotate_by(rotation)
            if item.get("maximized"):
                window.maximize_window()

    def paintEvent(self, event) -> None:
        self.frame_counter += 1
        elapsed = time.perf_counter() - self.fps_started
        if elapsed >= 1.0:
            self.ui_fps = self.frame_counter / elapsed
            self.frame_counter = 0
            self.fps_started = time.perf_counter()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient_top = QColor("#07141E")
        gradient_bottom = QColor("#02070C")
        painter.fillRect(self.rect(), gradient_bottom)

        if self.show_camera and not self.camera_pixmap.isNull():
            painter.setOpacity(0.20)
            x = (self.width() - self.camera_pixmap.width()) // 2
            y = 70 + (max(1, self.height() - 70) - self.camera_pixmap.height()) // 2
            painter.drawPixmap(x, y, self.camera_pixmap)
            painter.setOpacity(1.0)

        painter.fillRect(QRect(0, 70, self.width(), self.height() - 70), QColor(4, 12, 18, 120))
        painter.setPen(QPen(QColor(70, 204, 235, 30), 1))
        for x in range(0, self.width(), 54):
            painter.drawLine(x, 70, x, self.height())
        for y in range(70, self.height(), 54):
            painter.drawLine(0, y, self.width(), y)

        for particle in self.particles:
            x = int(particle["x"] * self.width())
            y = int(70 + particle["y"] * max(1, self.height() - 70))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(103, 220, 250, 85))
            painter.drawEllipse(QPoint(x, y), int(particle["r"]), int(particle["r"]))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(5, 16, 25, 248)))
        painter.drawRect(0, 0, self.width(), 70)
        painter.setPen(QColor("#8BE9FF"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(13)
        painter.setFont(font)
        painter.drawText(22, 31, "NEXUS • ULTRON / HOLODESK")
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#6FB8C9"))
        painter.drawText(22, 52, f"REACTOR CONSOLE • {APP_VERSION}")
        painter.setPen(QColor("#C5E9F2"))
        painter.drawText(270, 31, f"Gesture: {self.gesture_text}")
        painter.setPen(QColor("#6FA6B3"))
        painter.drawText(270, 51, self.hand_detail[:70])
        painter.setPen(QColor("#72CFE8"))
        painter.drawText(
            max(500, self.width() - 650), 44,
            f"UI {self.ui_fps:.0f} FPS • CAM {self.camera_fps:.0f} • HAND {self.tracking_fps:.0f} • GPU/Qt {'ON' if WEBENGINE_AVAILABLE else 'BASE'}"
        )

        if self.pointer.x() >= 0:
            painter.setPen(QPen(QColor("#8BE9FF"), 2))
            painter.setBrush(QBrush(QColor(139, 233, 255, 40)))
            painter.drawEllipse(self.pointer, 18, 18)
            painter.setBrush(QBrush(QColor("#8BE9FF")))
            painter.drawEllipse(self.pointer, 4, 4)
        if self.eye_tracking_enabled and self.eye_pointer.x() >= 0:
            painter.setPen(QPen(QColor("#FFDD7A"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.eye_pointer, 12, 8)
            painter.drawLine(self.eye_pointer.x() - 17, self.eye_pointer.y(), self.eye_pointer.x() + 17, self.eye_pointer.y())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "dashboard"):
            self.dashboard.setGeometry(10, 76, max(900, self.width() - 20), max(540, self.height() - 86))
            self.dashboard.lower()

    def close_all_resources(self) -> None:
        try:
            self.keyboard_overlay.clear()
            self.toast_overlay.hide_now()
            self._click_queue.put_nowait(None)
        except Exception:
            pass
        self.stop_companion()
        tracking_worker = self.tracking_worker
        camera_worker = self.camera_worker
        self.tracking_worker = None
        self.camera_worker = None
        if tracking_worker is not None:
            tracking_worker.stop()
        if camera_worker is not None:
            camera_worker.stop()
        if tracking_worker is not None:
            tracking_worker.join(timeout=2.0)
        if camera_worker is not None:
            camera_worker.join(timeout=2.0)


class ControlCenter(QWidget):
    def __init__(self, canvas: HoloCanvas):
        super().__init__()
        self.canvas = canvas
        layout = QVBoxLayout(self)
        title = QLabel("ULTRON CONTROL CENTER")
        title.setStyleSheet("color:#8BE9FF;font-size:18px;font-weight:800;padding:6px;")
        layout.addWidget(title)
        grid = QGridLayout()
        items = [
            ("Mission Builder", canvas.add_mission_builder_window),
            ("Self Edit", canvas.add_self_edit_window),
            ("World Map", canvas.add_world_map_window), ("Future Self", canvas.add_future_self_window),
            ("ZIP Builder", canvas.add_zip_builder_window),
            ("Windows", canvas.add_windows_manager), ("AI", canvas.add_ai_window),
            ("Browser", canvas.add_browser_window), ("Notes", canvas.add_text_window),
            ("Video", canvas.add_video_window), ("Music", canvas.add_music_window),
            ("Calculator", canvas.add_calculator_window), ("Calendar", canvas.add_calendar_window),
            ("Weather", canvas.add_weather_window), ("Clock", canvas.add_clock_window),
            ("Voice", canvas.add_voice_window), ("Phone", canvas.add_phone_window),
            ("Windows Keyboard", canvas.open_windows_keyboard),
        ]
        for index, (label, callback) in enumerate(items):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cb=callback: cb())
            grid.addWidget(button, index // 3, index % 3)
        layout.addLayout(grid)
        options = QHBoxLayout()
        self.eye = QCheckBox("Eye tracking")
        self.eye.setChecked(canvas.eye_tracking_enabled)
        self.eye.toggled.connect(canvas.set_eye_tracking)
        self.eye_cursor = QCheckBox("Eye cursor")
        self.eye_cursor.setChecked(canvas.eye_cursor_enabled)
        self.eye_cursor.toggled.connect(canvas.set_eye_cursor)
        self.performance = QCheckBox("Performance mode")
        self.performance.setChecked(canvas.settings.performance_mode)
        self.performance.toggled.connect(canvas.set_performance_mode)
        self.global_hand = QCheckBox("Global hand control")
        self.global_hand.setChecked(canvas.settings.global_hand_control)
        self.global_hand.toggled.connect(canvas.set_global_hand_control)
        options.addWidget(self.eye)
        options.addWidget(self.eye_cursor)
        options.addWidget(self.performance)
        options.addWidget(self.global_hand)
        layout.addLayout(options)
        sensitivity = QHBoxLayout()
        sensitivity.addWidget(QLabel("Air-typing sensitivity"))
        self.sens_slider = QSlider(Qt.Orientation.Horizontal)
        self.sens_slider.setRange(5, 40)
        self.sens_slider.setValue(int(round(canvas.settings.tap_sensitivity * 10)))
        self.sens_value = QLabel(f"{canvas.settings.tap_sensitivity:.1f}x")
        self.sens_slider.valueChanged.connect(self._sensitivity_changed)
        sensitivity.addWidget(self.sens_slider, 1)
        sensitivity.addWidget(self.sens_value)
        layout.addLayout(sensitivity)
        workspace = QHBoxLayout()
        save = QPushButton("Save Workspace")
        load = QPushButton("Load Workspace")
        settings = QPushButton("Settings")
        save.clicked.connect(lambda: canvas.save_workspace())
        load.clicked.connect(lambda: canvas.load_workspace())
        settings.clicked.connect(lambda: canvas.add_settings_window())
        workspace.addWidget(save)
        workspace.addWidget(load)
        workspace.addWidget(settings)
        layout.addLayout(workspace)
        self.setStyleSheet(button_style() + "QCheckBox{color:#DDF7FF;padding:8px;} QLabel{color:#DDF7FF;}")

    def _sensitivity_changed(self, value: int) -> None:
        factor = value / 10.0
        self.sens_value.setText(f"{factor:.1f}x")
        self.canvas.set_tap_sensitivity(factor)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(f"{APP_NAME} — Reactor Console")
        self.resize(1380, 860)
        self.setMinimumSize(1040, 680)
        self.canvas = HoloCanvas(settings)
        self.setCentralWidget(self.canvas)
        self.setStyleSheet("QMainWindow{background:#03080D;}QToolTip{color:#EAFBFF;background:#10222D;border:1px solid #4EA7C1;}")
        self.create_top_controls()
        self.create_menu()
        self._force_exit = False
        self._tray_notice_shown = False
        self._jarvis_listening_logged = False
        self.jarvis_voice = JarvisVoiceController(self.canvas, self)
        self.jarvis_voice.status_changed.connect(self._voice_status_changed)
        self.create_tray_icon()

    @staticmethod
    def _build_tray_icon() -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#62DFFF"), 4))
        painter.setBrush(QBrush(QColor("#082B3A")))
        painter.drawEllipse(7, 7, 50, 50)
        painter.setPen(QPen(QColor("#EAFBFF"), 3))
        painter.drawEllipse(20, 20, 24, 24)
        painter.end()
        return QIcon(pixmap)

    def create_tray_icon(self) -> None:
        self.tray_icon: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self._build_tray_icon()
        self.setWindowIcon(icon)
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("NEXUS - ULTRON is running")
        menu = QMenu()

        show_action = QAction("Open NEXUS", self)
        show_action.triggered.connect(self.show_from_tray)
        menu.addAction(show_action)

        control_action = QAction("ULTRON Control Center", self)
        control_action.triggered.connect(self.open_control_center_from_tray)
        menu.addAction(control_action)
        menu.addSeparator()

        exit_action = QAction("Exit NEXUS", self)
        exit_action.triggered.connect(self.quit_app)
        menu.addAction(exit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self.tray_icon = tray

    def _tray_activated(self, reason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def open_control_center_from_tray(self) -> None:
        self.show_from_tray()
        self.open_control_center()

    def quit_app(self) -> None:
        self._force_exit = True
        self.close()
        QApplication.quit()

    def _voice_status_changed(self, message: str) -> None:
        # Surface ULTRON state in the title bar and activity panel.
        self.setWindowTitle(f"{APP_NAME} — Reactor Console — {message}")
        try:
            dashboard = getattr(self.canvas, "dashboard", None)
            if dashboard is not None and hasattr(dashboard, "log"):
                if message == "ULTRON • LISTENING":
                    if self._jarvis_listening_logged:
                        return
                    self._jarvis_listening_logged = True
                detail = message.removeprefix("ULTRON • ").removeprefix("VOICE • ")
                dashboard.log("ULTRON", detail)
        except Exception:
            pass

    def create_top_controls(self) -> None:
        self.controls = QFrame(self.canvas)
        self.controls.setGeometry(self.width() - 440, 8, 420, 54)
        self.controls.setStyleSheet("QFrame{background:rgba(12,33,45,225);border:1px solid rgba(90,220,255,80);border-radius:14px;}" + button_style())
        layout = QHBoxLayout(self.controls)
        layout.setContentsMargins(7, 7, 7, 7)
        for label, callback in [
            ("ULTRON", self.open_control_center),
            ("Air Menu", self.canvas.open_air_menu),
            ("Save", self.canvas.save_workspace),
            ("Monitor", self.move_to_next_monitor),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cb=callback: cb())
            layout.addWidget(button)
        self.controls.raise_()

    def create_menu(self) -> None:
        app_menu = self.menuBar().addMenu("HoloDesk")
        actions = [
            ("Control Center", self.open_control_center),
            ("Save Workspace", self.canvas.save_workspace),
            ("Load Workspace", self.canvas.load_workspace),
            ("Settings", self.canvas.add_settings_window),
            ("Exit NEXUS", self.quit_app),
        ]
        for label, callback in actions:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, cb=callback: cb())
            app_menu.addAction(action)
        window_menu = self.menuBar().addMenu("Active Window")
        for label, callback in [
            ("Maximize", lambda: self.canvas.active_window.maximize_window() if self.canvas.active_window else None),
            ("Restore", lambda: self.canvas.active_window.restore_window() if self.canvas.active_window else None),
            ("Snap Left", lambda: self.canvas.active_window.snap_left() if self.canvas.active_window else None),
            ("Snap Right", lambda: self.canvas.active_window.snap_right() if self.canvas.active_window else None),
            ("Rotate +15°", lambda: self.canvas.active_window.rotate_by(15) if self.canvas.active_window else None),
            ("Close", lambda: self.canvas.active_window.close() if self.canvas.active_window else None),
        ]:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, cb=callback: cb())
            window_menu.addAction(action)
        self.menuBar().setStyleSheet("QMenuBar{background:#07141E;color:#DDF7FF;}QMenuBar::item:selected{background:#17495D;}QMenu{background:#0A1A25;color:#DDF7FF;border:1px solid #28758E;}QMenu::item:selected{background:#225C70;}")

    def open_control_center(self) -> None:
        self.canvas.place_window(VirtualWindow(self.canvas, "ULTRON Control Center", ControlCenter(self.canvas), 650, 500, "control_center"))

    def move_to_next_monitor(self) -> None:
        screens = QGuiApplication.screens()
        if len(screens) <= 1:
            return
        current = self.screen()
        try:
            index = screens.index(current)
        except ValueError:
            index = 0
        target = screens[(index + 1) % len(screens)]
        geo = target.availableGeometry()
        self.move(geo.topLeft() + QPoint(40, 40))
        self.resize(min(self.width(), geo.width() - 80), min(self.height(), geo.height() - 80))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "controls"):
            self.controls.setGeometry(self.width() - 440, 8, 420, 54)
        for window in self.canvas.windows:
            if window.maximized:
                window.maximize_window()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self._hide_to_tray()

    def _hide_to_tray(self) -> None:
        if self.tray_icon is None or self._force_exit:
            return
        self.hide()
        if not self._tray_notice_shown:
            self.tray_icon.showMessage(
                "NEXUS is still running",
                "ULTRON and computer controls remain active in the background.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            self._tray_notice_shown = True

    def closeEvent(self, event) -> None:
        if not self._force_exit and self.tray_icon is not None:
            event.ignore()
            self._hide_to_tray()
            return
        try:
            if hasattr(self, "jarvis_voice"):
                self.jarvis_voice.stop()
        except Exception:
            pass
        try:
            self.canvas.save_workspace(show_message=False)
        except Exception:
            pass
        self.canvas.close_all_resources()
        super().closeEvent(event)


def enable_windows_dpi_awareness() -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> None:
    enable_windows_dpi_awareness()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Segoe UI", 10))
    settings = AppSettings.load()
    registration = RegistrationGate(settings)
    registration.showMaximized()
    if registration.exec() != QDialog.DialogCode.Accepted or not registration.session:
        sys.exit(0)
    window = MainWindow(settings)
    app.aboutToQuit.connect(window.canvas.close_all_resources)
    window._on_supabase_authenticated(registration.session)
    if window.tray_icon is None:
        window.show()
    else:
        window.tray_icon.showMessage(
            APP_NAME,
            "Signed in and running in the background. Open NEXUS from the system tray.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

