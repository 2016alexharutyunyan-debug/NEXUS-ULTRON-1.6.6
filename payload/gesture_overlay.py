"""Click-through overlays for NEXUS ULTRON 1.6.6.

KeyboardOverlay : while air-typing, draws a dot on the Windows On-Screen Keyboard for every
                  fingertip (so you can SEE which key each finger is over) and a flash where a
                  key was pressed.
ToastOverlay    : short status text (e.g. BACKSPACE) near the bottom of the screen.

Both windows are frameless, always-on-top, transparent for mouse input and never take focus,
so they cannot disturb the application you are typing into.
Coordinates passed in are PHYSICAL screen pixels (what Win32 returns).
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QRect, QTimer, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowTransparentForInput
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


def _device_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


class _BaseOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None, _FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class KeyboardOverlay(_BaseOverlay):
    MARGIN = 14

    def __init__(self) -> None:
        super().__init__()
        self._rect_phys: Optional[tuple[int, int, int, int]] = None
        self._dots: list[tuple[float, float, int, str, float]] = []
        self._flashes: list[tuple[float, float, float, str]] = []
        self._ratio = 1.0
        self._origin = (0.0, 0.0)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # -- public API -------------------------------------------------------
    def set_state(self, rect_phys: Optional[tuple[int, int, int, int]], dots: list[tuple[float, float, int, str, float]]) -> None:
        if rect_phys is None:
            self.clear()
            return
        if rect_phys != self._rect_phys:
            self._rect_phys = rect_phys
            self._apply_geometry()
        self._dots = dots
        if not self.isVisible():
            self.show()
            self.raise_()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def flash(self, x_phys: float, y_phys: float, label: str = "") -> None:
        self._flashes.append((x_phys, y_phys, time.monotonic(), label))

    def clear(self) -> None:
        self._rect_phys = None
        self._dots = []
        self._flashes = []
        self._timer.stop()
        self.hide()

    # -- internals --------------------------------------------------------
    def _apply_geometry(self) -> None:
        if self._rect_phys is None:
            return
        ratio = _device_ratio()
        self._ratio = ratio
        left, top, right, bottom = self._rect_phys
        x = left / ratio - self.MARGIN
        y = top / ratio - self.MARGIN
        w = (right - left) / ratio + 2 * self.MARGIN
        h = (bottom - top) / ratio + 2 * self.MARGIN
        self._origin = (x, y)
        self.setGeometry(QRect(int(x), int(y), int(w), int(h)))

    def _local(self, x_phys: float, y_phys: float) -> QPointF:
        return QPointF(x_phys / self._ratio - self._origin[0], y_phys / self._ratio - self._origin[1])

    def _tick(self) -> None:
        now = time.monotonic()
        self._flashes = [f for f in self._flashes if now - f[2] < 0.35]
        self.update()

    def paintEvent(self, _event) -> None:
        if self._rect_phys is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left, top, right, bottom = self._rect_phys
        tl = self._local(left, top)
        br = self._local(right, bottom)
        frame = QRectF(tl, br)
        painter.setPen(QPen(QColor(100, 230, 255, 170), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor(60, 190, 230, 18)))
        painter.drawRoundedRect(frame, 8, 8)
        font = QFont("Segoe UI", 8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(150, 240, 255, 210))
        painter.drawText(frame.adjusted(6, -12, 0, 0).topLeft() + QPointF(0, -2), "AIR TYPING • tap a finger to press the key under its dot")

        palette = (QColor(255, 214, 90, 235), QColor(120, 255, 190, 235))
        for x, y, hand_idx, finger, meter in self._dots:
            center = self._local(x, y)
            color = palette[hand_idx % 2]
            if meter >= 0.5:      # the finger is bending: turn red as it approaches a press
                mix = min(1.0, (meter - 0.5) / 0.5)
                color = QColor(int(color.red() + (255 - color.red()) * mix), int(color.green() * (1 - 0.8 * mix)), int(color.blue() * (1 - 0.8 * mix)), 240)
            radius = (8.0 if finger == "index" else 6.0) + 7.0 * min(1.0, meter)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 1.5))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(center, radius, radius)

        now = time.monotonic()
        for x, y, started, _label in self._flashes:
            age = (now - started) / 0.35
            if age >= 1.0:
                continue
            center = self._local(x, y)
            alpha = int(255 * (1.0 - age))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, alpha), 3))
            radius = 10 + 26 * age
            painter.drawEllipse(center, radius, radius)
        painter.end()


class ToastOverlay(_BaseOverlay):
    WIDTH = 420
    HEIGHT = 64

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._until = 0.0
        self.resize(self.WIDTH, self.HEIGHT)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)

    def show_text(self, text: str, seconds: float = 1.2) -> None:
        self._text = text
        self._until = time.monotonic() + seconds
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.setGeometry(
                geo.x() + (geo.width() - self.WIDTH) // 2,
                geo.y() + geo.height() - self.HEIGHT - 70,
                self.WIDTH,
                self.HEIGHT,
            )
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()
        self._timer.start(int(seconds * 1000))

    def hide_now(self) -> None:
        self._timer.stop()
        self.hide()

    def _expire(self) -> None:
        if time.monotonic() >= self._until - 0.02:
            self.hide()
        else:
            self._timer.start(max(30, int((self._until - time.monotonic()) * 1000)))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(100, 230, 255, 200), 2))
        painter.setBrush(QBrush(QColor(5, 20, 30, 225)))
        painter.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 14, 14)
        font = QFont("Segoe UI", 13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(220, 250, 255))
        painter.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()
