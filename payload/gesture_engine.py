"""NEXUS ULTRON 1.6.6 gesture engine.

Pure Python (no Qt, OpenCV or MediaPipe), so every rule here can be unit-tested.

Two detectors live here:

* PalmSwipeDetector  - open palm moves from the bottom of the camera view upwards
                       -> one Backspace (deletes the last character or the selection).
* FingerTapDetector  - every finger of both hands is tracked separately; a quick
                       flexion of one finger is a "key press" at the place where the
                       fingertip was hovering.

Why a new engine (what was wrong in 1.6.5):

* Hand identity was "Left/Right label + slot".  MediaPipe flips that label from frame
  to frame, so the swipe history was wiped and a swipe could never accumulate.
  Here hands are tracked by nearest-neighbour matching of their position instead.
* One frame where the hand did not count as "open" erased the whole swipe history.
  Here a short grace period is allowed.
* "Open palm" needed an absolute finger spread; a relaxed or distant hand failed.
  Here everything is measured relative to the size of the hand.
* Finger taps were measured against raw image axes; a rotated wrist or a closing
  fist produced false taps and light taps were missed.  Here the flexion of a
  finger is measured along the hand's own axis (rotation invariant), normalised by
  palm size, and a tap must be an *isolated* finger movement.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional, Sequence

DEFAULT_ASPECT = 16.0 / 9.0

FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")
LONG_FINGERS = ("index", "middle", "ring", "pinky")
TIP = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
MCP = {"thumb": 2, "index": 5, "middle": 9, "ring": 13, "pinky": 17}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _aspect_of(hand: dict[str, Any]) -> float:
    try:
        value = float(hand.get("aspect", DEFAULT_ASPECT))
        return value if 0.5 <= value <= 4.0 else DEFAULT_ASPECT
    except (TypeError, ValueError):
        return DEFAULT_ASPECT


def _iso(points: Sequence[Sequence[float]], index: int, aspect: float) -> tuple[float, float]:
    """Landmark in isotropic units (1.0 = camera frame height)."""
    return points[index][0] * aspect, points[index][1]


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_center(points: Sequence[Sequence[float]], aspect: float = DEFAULT_ASPECT) -> tuple[float, float]:
    ids = (0, 5, 9, 13, 17)
    return (
        sum(points[i][0] for i in ids) / len(ids) * aspect,
        sum(points[i][1] for i in ids) / len(ids),
    )


def hand_is_open(hand: dict[str, Any]) -> bool:
    """Lenient 'open palm' test used by the swipe: palm_open flag or >=3 long fingers up."""
    if hand.get("palm_open"):
        return True
    fingers = hand.get("fingers") or {}
    return sum(1 for name in LONG_FINGERS if fingers.get(name)) >= 3


# --------------------------------------------------------------------------- #
# Stable hand identities
# --------------------------------------------------------------------------- #
class HandAssociator:
    """Gives each hand a stable id by nearest-neighbour matching (ignores Left/Right labels)."""

    def __init__(self, max_distance: float = 0.45, ttl: float = 0.5):
        self.max_distance = max_distance
        self.ttl = ttl
        self._tracks: dict[int, tuple[float, float, float]] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._tracks.clear()

    def assign(self, hands: Sequence[dict[str, Any]], now: float) -> list[int]:
        for tid in [t for t, (_x, _y, seen) in self._tracks.items() if now - seen > self.ttl]:
            del self._tracks[tid]
        centers = []
        for hand in hands:
            centers.append(palm_center(hand["points"], _aspect_of(hand)))
        pairs = sorted(
            (math.hypot(cx - tx, cy - ty), hi, tid)
            for hi, (cx, cy) in enumerate(centers)
            for tid, (tx, ty, _seen) in self._tracks.items()
        )
        ids: list[Optional[int]] = [None] * len(hands)
        used: set[int] = set()
        for distance, hi, tid in pairs:
            if distance > self.max_distance:
                break
            if ids[hi] is not None or tid in used:
                continue
            ids[hi] = tid
            used.add(tid)
        result: list[int] = []
        for hi, tid in enumerate(ids):
            if tid is None:
                tid = self._next_id
                self._next_id += 1
            self._tracks[tid] = (centers[hi][0], centers[hi][1], now)
            result.append(tid)
        return result


# --------------------------------------------------------------------------- #
# Palm swipe up  ->  Backspace
# --------------------------------------------------------------------------- #
@dataclass
class SwipeEvent:
    hand_id: int
    rise: float
    speed: float
    y: float
    start_t: float = 0.0      # time the upward movement began (lowest point)


class _PalmTrack:
    __slots__ = ("born", "samples", "last_seen", "locked_y", "still_t", "still_y", "ready", "ready_from")

    def __init__(self, now: float):
        self.born = now
        self.still_t = now
        self.still_y: Optional[float] = None
        self.ready = False
        self.ready_from = 0.0
        self.samples: deque[tuple[float, float, float, bool]] = deque()
        self.last_seen = now
        self.locked_y: Optional[float] = None


class PalmSwipeDetector:
    """Open palm travels upwards through the camera view -> one SwipeEvent.

    rise      minimum vertical travel (fraction of frame height) inside `window`
    dwell     the palm must pause this long (barely moving) before the rise, so a hand
              that is merely being raised into view is not counted (0 disables)
    cooldown  minimum time between two swipes
    rearm_drop after a swipe the hand must come down by this much before the next one
    """

    def __init__(
        self,
        rise: float = 0.16,
        window: float = 0.60,
        min_start_y: float = 0.34,
        min_speed: float = 0.25,
        cooldown: float = 0.70,
        rearm_drop: float = 0.10,
        dwell: float = 0.10,
        grace: float = 0.40,
    ):
        self.rise = rise
        self.window = window
        self.min_start_y = min_start_y
        self.min_speed = min_speed
        self.cooldown = cooldown
        self.rearm_drop = rearm_drop
        self.dwell = dwell
        self.grace = grace
        self.assoc = HandAssociator()
        self.tracks: dict[int, _PalmTrack] = {}
        self.last_fire = -999.0

    def reset(self) -> None:
        self.assoc.reset()
        self.tracks.clear()

    def update(self, hands: Sequence[dict[str, Any]], now: float, rise: Optional[float] = None) -> Optional[SwipeEvent]:
        need_rise = self.rise if rise is None else rise
        ids = self.assoc.assign(hands, now)
        current: dict[int, tuple[float, float, bool]] = {}
        for hand, hid in zip(hands, ids):
            aspect = _aspect_of(hand)
            cx, cy = palm_center(hand["points"], aspect)
            track = self.tracks.get(hid)
            if track is None:
                track = self.tracks[hid] = _PalmTrack(now)
            is_open = hand_is_open(hand)
            # "ready" = the hand has paused for `dwell` seconds since it appeared / since the last swipe.
            if track.still_y is None or abs(cy - track.still_y) > 0.05:
                track.still_y = cy
                track.still_t = now
            elif now - track.still_t >= self.dwell and not track.ready:
                track.ready = True
                track.ready_from = track.still_t
            track.samples.append((now, cx, cy, is_open))
            track.last_seen = now
            while track.samples and now - track.samples[0][0] > self.window + 0.15:
                track.samples.popleft()
            current[hid] = (cx, cy, is_open)

        for hid in [h for h, t in self.tracks.items() if now - t.last_seen > self.grace]:
            del self.tracks[hid]

        if now - self.last_fire < self.cooldown:
            return None

        best: Optional[SwipeEvent] = None
        for hid, (cx, cy, is_open) in current.items():
            track = self.tracks[hid]
            if track.locked_y is not None:
                if cy >= track.locked_y + self.rearm_drop:
                    track.locked_y = None
                else:
                    continue
            if not is_open:
                continue
            window = [s for s in track.samples if now - s[0] <= self.window]
            if len(window) < 3:
                continue
            lowest = max(window, key=lambda s: s[2])
            if lowest[2] < self.min_start_y:
                continue
            travelled = lowest[2] - cy
            elapsed = now - lowest[0]
            if travelled < need_rise or elapsed <= 0.0:
                continue
            speed = travelled / elapsed
            if speed < self.min_speed:
                continue
            if abs(cx - lowest[1]) > travelled * 1.1:
                continue
            if self.dwell > 0.0 and not (track.ready and track.ready_from <= lowest[0] + 0.03):
                continue          # the pause must come BEFORE the rise started
            after = [s for s in window if s[0] >= lowest[0]]
            if sum(1 for s in after if s[3]) < 0.6 * len(after):
                continue
            if len(after) >= 3:
                steps = list(zip(after, after[1:]))
                upward = sum(1 for a, b in steps if b[2] <= a[2] + 0.004)
                if upward < 0.6 * len(steps):
                    continue
            event = SwipeEvent(hid, travelled, speed, cy, lowest[0])
            if best is None or event.rise > best.rise:
                best = event

        if best is not None:
            self.last_fire = now
            track = self.tracks.get(best.hand_id)
            if track is not None:
                track.locked_y = best.y
                track.ready = False
                track.still_y = None
        return best


# --------------------------------------------------------------------------- #
# Per-finger tap detection
# --------------------------------------------------------------------------- #
@dataclass
class TapEvent:
    finger: str
    hand_id: int
    x: float          # normalised camera x of the fingertip BEFORE the tap started
    y: float          # normalised camera y of the fingertip BEFORE the tap started
    strength: float   # drop / threshold (>= 1.0)


class _FingerState:
    __slots__ = ("samples", "armed", "last_fire", "diffs")

    def __init__(self) -> None:
        self.diffs: deque[float] = deque(maxlen=16)
        self.samples: deque[tuple[float, float, float, float, int]] = deque(maxlen=18)
        self.armed = True
        self.last_fire = -999.0


class _HandState:
    __slots__ = ("fingers", "lockout_until", "last_seen")

    def __init__(self, now: float) -> None:
        self.fingers = {name: _FingerState() for name in FINGER_NAMES}
        self.lockout_until = 0.0
        self.last_seen = now


def finger_signals(points: Sequence[Sequence[float]], aspect: float) -> Optional[dict[str, tuple[float, float, float, int]]]:
    """Return {finger: (flexion, tip_x, tip_y, mode)} or None when the hand is too small/degenerate.

    flexion is a dimensionless extension value that DROPS when the finger bends:
      mode 0 : projection of (tip - knuckle) on the hand axis, divided by palm length
               (rotation invariant)
      mode 1 : used when the hand points at the camera (palm foreshortened):
               (knuckle_y - tip_y) / palm width
      mode 2 : thumb, distance tip -> index knuckle / palm length
    """
    wrist = _iso(points, 0, aspect)
    m9 = _iso(points, 9, aspect)
    palm_len = _dist(wrist, m9)
    palm_w = _dist(_iso(points, 5, aspect), _iso(points, 17, aspect))
    if palm_w < 0.035 or palm_len < 1e-4:
        return None
    mode = 0 if palm_len >= 0.55 * palm_w else 1
    ux = (m9[0] - wrist[0]) / palm_len
    uy = (m9[1] - wrist[1]) / palm_len
    out: dict[str, tuple[float, float, float, int]] = {}
    for name in LONG_FINGERS:
        tip = _iso(points, TIP[name], aspect)
        mcp = _iso(points, MCP[name], aspect)
        if mode == 0:
            flex = ((tip[0] - mcp[0]) * ux + (tip[1] - mcp[1]) * uy) / palm_len
        else:
            flex = (mcp[1] - tip[1]) / palm_w
        out[name] = (flex, points[TIP[name]][0], points[TIP[name]][1], mode)
    thumb_tip = _iso(points, 4, aspect)
    thumb_flex = _dist(thumb_tip, _iso(points, 5, aspect)) / max(palm_len, 0.6 * palm_w)
    out["thumb"] = (thumb_flex, points[4][0], points[4][1], 2)
    return out


class FingerTapDetector:
    """Detects quick, isolated flexion of individual fingers (all ten fingers)."""

    BASE_DROP = 0.11      # flexion units (palm lengths) that must be lost inside WINDOW
    WINDOW = 0.30         # seconds
    MIN_GAP = 0.14        # seconds between two taps of the same finger
    SMOOTH = 0.70         # EMA factor for the flexion signal (1.0 = no smoothing)
    NOISE_K = 6.0         # threshold is at least NOISE_K x median frame-to-frame jitter

    def __init__(self, sensitivity: float = 1.0):
        self.sensitivity = clamp(sensitivity, 0.3, 4.0)
        self.assoc = HandAssociator()
        self.hands: dict[int, _HandState] = {}
        # live meters aligned with the `hands` list given to update(): finger -> drop / threshold
        self.meters: list[dict[str, float]] = []

    def reset(self) -> None:
        self.assoc.reset()
        self.hands.clear()
        self.meters = []

    def set_sensitivity(self, value: float) -> None:
        self.sensitivity = clamp(float(value), 0.3, 4.0)

    @property
    def threshold(self) -> float:
        return self.BASE_DROP / self.sensitivity

    def update(self, hands: Sequence[dict[str, Any]], now: float) -> list[TapEvent]:
        usable = list(hands)      # handedness score is NOT detection confidence (it can be 0/None) - never filter on it
        self.meters = [{} for _ in usable]
        ids = self.assoc.assign(usable, now)
        for hid in [h for h, s in self.hands.items() if now - s.last_seen > 0.6]:
            del self.hands[hid]

        events: list[TapEvent] = []
        for hand_pos, (hand, hid) in enumerate(zip(usable, ids)):
            signals = finger_signals(hand["points"], _aspect_of(hand))
            state = self.hands.get(hid)
            if state is None:
                state = self.hands[hid] = _HandState(now)
            state.last_seen = now
            if signals is None:
                continue

            drops: dict[str, float] = {}
            prev_drops: dict[str, float] = {}
            anchors: dict[str, tuple[float, float]] = {}
            for name in FINGER_NAMES:
                flex, tip_x, tip_y, mode = signals[name]
                f = state.fingers[name]
                if f.samples and f.samples[-1][4] == mode:
                    flex = f.samples[-1][1] + self.SMOOTH * (flex - f.samples[-1][1])
                    f.diffs.append(abs(flex - f.samples[-1][1]))
                elif f.samples:
                    f.samples.clear()
                f.samples.append((now, flex, tip_x, tip_y, mode))
                recent = [s for s in f.samples if now - s[0] <= self.WINDOW and s[4] == mode]
                best = max(recent, key=lambda s: s[1])
                drops[name] = best[1] - flex
                prev_drops[name] = (best[1] - f.samples[-2][1]) if len(f.samples) >= 2 and f.samples[-2][4] == mode else 0.0
                anchors[name] = (best[2], best[3])

            if now < state.lockout_until:
                for f in state.fingers.values():
                    f.armed = False
                continue

            # Adaptive noise floor: a shaky/distant hand raises the threshold instead of typing garbage.
            medians = []
            for name in LONG_FINGERS:
                diffs = sorted(state.fingers[name].diffs)
                if len(diffs) >= 6:
                    medians.append(diffs[len(diffs) // 2])
            hand_noise = sorted(medians)[len(medians) // 2] if medians else 0.0
            thr = max(self.threshold, self.NOISE_K * hand_noise)
            self.meters[hand_pos] = {n: clamp(drops[n] / max(thr, 1e-6), 0.0, 1.5) for n in FINGER_NAMES}

            for name in FINGER_NAMES:
                f = state.fingers[name]
                if not f.armed and now - f.last_fire >= 0.12 and drops[name] < 0.5 * thr:
                    f.armed = True

            candidates: list[str] = []
            for name in LONG_FINGERS:
                f = state.fingers[name]
                if not f.armed or now - f.last_fire < self.MIN_GAP or drops[name] < thr:
                    continue
                if prev_drops[name] < 0.7 * thr and drops[name] < 2.0 * thr:   # single-frame spike = noise
                    continue
                others = sorted(drops[o] for o in LONG_FINGERS if o != name)
                if drops[name] - others[1] < 0.5 * thr:      # not isolated -> tilt / fist
                    continue
                candidates.append(name)
            thumb = state.fingers["thumb"]
            if thumb.armed and now - thumb.last_fire >= self.MIN_GAP and drops["thumb"] >= 1.7 * thr and prev_drops["thumb"] >= 1.2 * thr:
                if sorted(drops[o] for o in LONG_FINGERS)[1] < 0.5 * thr:
                    candidates.append("thumb")

            bent_together = sum(1 for n in LONG_FINGERS if state.fingers[n].armed and drops[n] >= thr)
            if bent_together >= 3:
                state.lockout_until = now + 0.45
                for f in state.fingers.values():
                    f.armed = False
                continue

            for name in candidates:
                f = state.fingers[name]
                f.armed = False
                f.last_fire = now
                x, y = anchors[name]
                events.append(TapEvent(name, hid, x, y, drops[name] / thr))
        return events


# --------------------------------------------------------------------------- #
# Camera -> on-screen keyboard mapping
# --------------------------------------------------------------------------- #
def map_camera_to_rect(
    x: float,
    y: float,
    rect: tuple[int, int, int, int],
    region: tuple[float, float, float, float] = (0.06, 0.94, 0.18, 0.80),
) -> tuple[float, float]:
    """Map a normalised camera point to a screen point inside the keyboard rectangle.

    `region` = (x0, x1, y0, y1): the part of the camera view that represents the keyboard.
    """
    x0, x1, y0, y1 = region
    fx = clamp((x - x0) / max(1e-6, x1 - x0), 0.005, 0.995)
    fy = clamp((y - y0) / max(1e-6, y1 - y0), 0.005, 0.995)
    left, top, right, bottom = rect
    return left + fx * (right - left), top + fy * (bottom - top)
