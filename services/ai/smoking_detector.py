"""
smoking_detector.py
───────────────────
Standalone smoking detection using YOLOv8 object detection.

Detection philosophy
────────────────────
Smoking is confirmed only when MULTIPLE signals agree:

  1. CIGARETTE   — a cigarette / cigar object is detected near the face/hand
  2. LIT TIP     — a small bright orange/red region at the cigarette tip
  3. SMOKE PLUME — a light-coloured, upward-drifting haze near the cigarette

Scoring:
  cigarette alone          →  "holding"           (score 2)
  cigarette + lit tip      →  "smoking_likely"    (score 4)
  cigarette + smoke        →  "smoking_likely"    (score 4)
  cigarette + tip + smoke  →  "smoking_confirmed" (score 6)
  tip/smoke without cig    →  ignored (too noisy — candles, steam, etc.)

This avoids false positives from:
  • unlit cigarettes being held
  • steam / fog / breath in cold weather
  • candles or lighters without a cigarette present
"""

import os
from pathlib import Path
from collections import deque, Counter

import cv2
import numpy as np
from ultralytics import YOLO

# ─────────────────────────────────────────────────────────────────────────────
# ✏️  CONFIGURABLE PATHS — change these to point at your weights files
# ─────────────────────────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # cv_backend/

MODEL_PATHS = {
    # Base YOLOv8 person detector (auto-downloaded by Ultralytics if absent)
    "person": str(_BASE_DIR / "trained-models" / "yolov8n.pt"),

    # Custom YOLOv8 cigarette detector (set to None to use colour heuristics)
    "cigarette": str(_BASE_DIR / "trained-models" / "cigarette_best.pt"),

    # Output storage roots (override if needed)
    "frames_dir": str(_BASE_DIR / "storage" / "smoking_frames"),
    "output_dir": str(_BASE_DIR / "storage" / "smoking_output"),
}

# ── tuneable constants ────────────────────────────────────────────────────────
CONF_THRESH       = 0.30   # YOLO detection confidence threshold
SMOKE_WINDOW      = 8      # temporal smoothing window (frames)
LIT_TIP_THRESH    = 0.18   # fraction of cigarette bbox that must be bright
SMOKE_AREA_THRESH = 400    # min pixel area for a smoke region
MAX_CIG_FACE_DIST = 0.45   # max normalised distance cig→face to count

# COCO class id for persons (YOLOv8 COCO-80)
PERSON_CLASS = 0

# ── colour ranges (HSV) for tip and smoke detection ──────────────────────────
# Lit cigarette tip: orange-red glow
TIP_LOWER  = np.array([5,  120, 180], dtype=np.uint8)
TIP_UPPER  = np.array([25, 255, 255], dtype=np.uint8)

# Smoke: near-white / light-grey with low saturation
SMOKE_LOWER = np.array([0,   0, 180], dtype=np.uint8)
SMOKE_UPPER = np.array([180, 40, 255], dtype=np.uint8)

# ── label display ─────────────────────────────────────────────────────────────
STATUS_COLORS = {
    "smoking_confirmed": (0,   0,   220),   # red
    "smoking_likely":    (0,  140,  255),   # orange
    "holding":           (0,  215,  255),   # yellow
    "clear":             (50, 205,   50),   # green
}

STATUS_PRIORITY = {
    "smoking_confirmed": 3,
    "smoking_likely":    2,
    "holding":           1,
    "clear":             0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _box_centre(box):
    """Return (cx, cy) of a xyxy box."""
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _box_diag(box):
    """Diagonal length of a xyxy box — used for normalised distances."""
    w = box[2] - box[0]
    h = box[3] - box[1]
    return max(float(np.sqrt(w * w + h * h)), 1.0)


def _normalised_dist(box_a, box_b):
    """Distance between centres of two boxes, normalised by box_a diagonal."""
    ca = _box_centre(box_a)
    cb = _box_centre(box_b)
    dx = ca[0] - cb[0]
    dy = ca[1] - cb[1]
    return float(np.sqrt(dx * dx + dy * dy)) / _box_diag(box_a)


def _crop(frame, box, pad=10):
    """Safe crop of a xyxy region from frame with optional padding."""
    h, w = frame.shape[:2]
    x1 = max(0, int(box[0]) - pad)
    y1 = max(0, int(box[1]) - pad)
    x2 = min(w, int(box[2]) + pad)
    y2 = min(h, int(box[3]) + pad)
    return frame[y1:y2, x1:x2], (x1, y1)


# ─────────────────────────────────────────────────────────────────────────────
# Signal detectors
# ─────────────────────────────────────────────────────────────────────────────

def detect_lit_tip(frame: np.ndarray, cig_box) -> tuple[bool, float]:
    """
    Look for an orange/red glow at or near the cigarette bounding box.
    Returns (found, coverage_ratio).
    """
    region, _ = _crop(frame, cig_box, pad=6)
    if region.size == 0:
        return False, 0.0

    hsv   = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask  = cv2.inRange(hsv, TIP_LOWER, TIP_UPPER)
    ratio = mask.sum() / 255 / max(region.shape[0] * region.shape[1], 1)
    return ratio > LIT_TIP_THRESH, round(float(ratio), 4)


def detect_smoke(frame: np.ndarray, cig_box, person_box) -> tuple[bool, float]:
    """
    Look for a light-coloured upward-drifting haze ABOVE the cigarette.

    Strategy:
      • Search in the region between the cigarette tip and the top of the
        person bounding box — smoke always rises.
      • Filter by colour (near-white, low saturation).
      • Require a minimum contiguous area to reject noise pixels.
    """
    h, w = frame.shape[:2]

    cig_top  = int(cig_box[1])
    pers_top = max(0, int(person_box[1]))
    pers_x1  = max(0, int(person_box[0]))
    pers_x2  = min(w, int(person_box[2]))

    if cig_top - pers_top < 20:
        return False, 0.0

    smoke_region = frame[pers_top:cig_top, pers_x1:pers_x2]
    if smoke_region.size == 0:
        return False, 0.0

    hsv  = cv2.cvtColor(smoke_region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, SMOKE_LOWER, SMOKE_UPPER)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    max_area    = max((cv2.contourArea(c) for c in contours), default=0.0)

    return max_area > SMOKE_AREA_THRESH, round(float(max_area), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Overlay drawing
# ─────────────────────────────────────────────────────────────────────────────

def draw_smoking_overlay(
    frame: np.ndarray,
    person_statuses: list[tuple[int, str, dict]],
    timestamp: float,
) -> np.ndarray:
    """
    Draw:
      • Coloured border around each person box
      • Status badge (top-right)
      • Signal pills below the badge
      • Timestamp (bottom-left)
    """
    frame = frame.copy()
    h, w  = frame.shape[:2]

    FONT       = cv2.FONT_HERSHEY_DUPLEX
    FONT_SCALE = 0.58
    THICKNESS  = 1
    PAD_X, PAD_Y = 10, 6
    ROW_GAP      = 6
    MARGIN_R     = 14
    MARGIN_T     = 14

    y_cursor = MARGIN_T

    for person_id, status, signals in person_statuses:
        color = STATUS_COLORS.get(status, (200, 200, 200))

        # person bounding box
        pbox = signals.get("person_box")
        if pbox is not None:
            cv2.rectangle(
                frame,
                (int(pbox[0]), int(pbox[1])),
                (int(pbox[2]), int(pbox[3])),
                color, 2, cv2.LINE_AA,
            )

        # cigarette box (yellow)
        cbox = signals.get("cig_box")
        if cbox is not None:
            cv2.rectangle(
                frame,
                (int(cbox[0]), int(cbox[1])),
                (int(cbox[2]), int(cbox[3])),
                (0, 255, 255), 1, cv2.LINE_AA,
            )

        # status badge
        badge_text = f"P{person_id}: {status.replace('_', ' ')}".upper()
        (tw, th), bl = cv2.getTextSize(badge_text, FONT, FONT_SCALE, THICKNESS)
        bw, bh = tw + PAD_X * 2, th + PAD_Y * 2 + bl
        x1, y1 = w - MARGIN_R - bw, y_cursor
        x2, y2 = w - MARGIN_R,      y_cursor + bh

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, cv2.FILLED)
        cv2.addWeighted(overlay, 0.60, frame, 0.40, 0, frame)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        cv2.putText(
            frame, badge_text, (x1 + PAD_X, y1 + PAD_Y + th),
            FONT, FONT_SCALE, (255, 255, 255), THICKNESS, cv2.LINE_AA,
        )
        y_cursor = y2 + ROW_GAP

        # signal pills
        pill = (
            f"cig={'Y' if signals.get('cig') else 'N'}  "
            f"tip={'Y' if signals.get('tip') else 'N'}({signals.get('tip_ratio', 0):.2f})  "
            f"smoke={'Y' if signals.get('smoke') else 'N'}({signals.get('smoke_area', 0):.0f}px)  "
            f"score={signals.get('score', 0)}"
        )
        (lw, lh), _ = cv2.getTextSize(pill, cv2.FONT_HERSHEY_PLAIN, 0.9, 1)
        lx = w - MARGIN_R - lw - PAD_X * 2
        cv2.rectangle(
            frame, (lx - 4, y_cursor), (w - MARGIN_R, y_cursor + lh + 6),
            (30, 30, 30), cv2.FILLED,
        )
        cv2.putText(
            frame, pill, (lx, y_cursor + lh + 2),
            cv2.FONT_HERSHEY_PLAIN, 0.9, (200, 200, 200), 1, cv2.LINE_AA,
        )
        y_cursor += lh + ROW_GAP + 6 + 10  # gap between persons

    # timestamp
    cv2.putText(
        frame, f"t = {timestamp:.2f}s",
        (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX,
        0.50, (220, 220, 220), 1, cv2.LINE_AA,
    )
    return frame


# ─────────────────────────────────────────────────────────────────────────────
# Temporal smoother
# ─────────────────────────────────────────────────────────────────────────────

class SmokingSmoother:
    """
    Per-person rolling majority vote over recent frames.
    Uses STATUS_PRIORITY to break ties in favour of the more severe label.
    """

    def __init__(self, window: int = SMOKE_WINDOW):
        self._window  = window
        self._buffers: dict[int, deque] = {}

    def smooth(self, person_id: int, status: str) -> str:
        if person_id not in self._buffers:
            self._buffers[person_id] = deque(maxlen=self._window)
        self._buffers[person_id].append(status)
        counts = Counter(self._buffers[person_id])
        return max(counts, key=lambda s: (counts[s], STATUS_PRIORITY.get(s, 0)))


# ─────────────────────────────────────────────────────────────────────────────
# Core detector
# ─────────────────────────────────────────────────────────────────────────────

class SmokingDetector:
    """
    Two-model pipeline:
      Model A (YOLOv8n)        — detects persons
      Model B (YOLOv8n custom) — detects cigarettes
                                 (falls back to colour heuristics if unavailable)

    Model paths are resolved from the MODULE_PATHS dict at the top of this file,
    but can be overridden per-instance for testing or multi-tenant deployments.
    """

    def __init__(
        self,
        person_model_path: str = MODEL_PATHS["person"],
        cig_model_path:    str | None = MODEL_PATHS["cigarette"],
    ):
        print(f"[SmokingDetector] Loading person detector from: {person_model_path}")
        self.person_model = YOLO(person_model_path)

        self.cig_model: YOLO | None = None
        if cig_model_path and Path(cig_model_path).exists():
            print(f"[SmokingDetector] Loading cigarette detector from: {cig_model_path}")
            self.cig_model = YOLO(cig_model_path)
        else:
            print(
                "[SmokingDetector] No cigarette model found — using colour/shape heuristics.\n"
                "                  Supply a YOLOv8 model via MODEL_PATHS['cigarette'] for better accuracy."
            )

        self.smoother = SmokingSmoother(window=SMOKE_WINDOW)

    # ── cigarette detection (heuristic fallback) ──────────────────────────────

    def _find_cigarettes_heuristic(
        self, frame: np.ndarray, person_box
    ) -> list:
        """
        When no dedicated cigarette model is available, search for thin
        bright-tipped objects in the hand/face region of the person box.
        Returns a list of pseudo-boxes [x1, y1, x2, y2] in frame coordinates.
        """
        px1, py1, px2, py2 = (int(v) for v in person_box)
        ph = py2 - py1
        region = frame[py1: py1 + int(ph * 0.60), px1:px2]
        if region.size == 0:
            return []

        hsv      = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        tip_mask = cv2.inRange(hsv, TIP_LOWER, TIP_UPPER)

        stick_lower = np.array([0,  0,  200], dtype=np.uint8)
        stick_upper = np.array([30, 40, 255], dtype=np.uint8)
        stick_mask  = cv2.inRange(hsv, stick_lower, stick_upper)

        combined = cv2.bitwise_or(tip_mask, stick_mask)
        kernel   = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < 10:
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            if ch / max(cw, 1) > 1.5 and area < 2000:  # tall & thin = cigarette
                boxes.append([px1 + x, py1 + y, px1 + x + cw, py1 + y + ch])
        return boxes

    # ── per-frame analysis ───────────────────────────────────────────────────

    def _analyse_frame(
        self, frame: np.ndarray, timestamp: float
    ) -> tuple[np.ndarray, list[dict]]:

        person_results  = self.person_model(frame, verbose=False, classes=[PERSON_CLASS])
        frame_records:   list[dict]                   = []
        person_statuses: list[tuple[int, str, dict]]  = []

        for r in person_results:
            if r.boxes is None or len(r.boxes) == 0:
                continue

            for person_id, box in enumerate(r.boxes.xyxy):
                pbox = box.cpu().numpy()
                conf = float(r.boxes.conf[person_id])
                if conf < CONF_THRESH:
                    continue

                # find cigarettes near this person
                if self.cig_model:
                    cig_res   = self.cig_model(frame, verbose=False)
                    cig_boxes = [
                        cb.cpu().numpy()
                        for cr in cig_res
                        if cr.boxes is not None
                        for cb in cr.boxes.xyxy
                        if _normalised_dist(pbox, cb.cpu().numpy()) < MAX_CIG_FACE_DIST
                    ]
                else:
                    cig_boxes = self._find_cigarettes_heuristic(frame, pbox)

                # score this person
                best_status  = "clear"
                best_signals: dict = {"person_box": pbox.tolist(), "score": 0}

                for cig_box in cig_boxes:
                    tip_found,   tip_ratio  = detect_lit_tip(frame, cig_box)
                    smoke_found, smoke_area = detect_smoke(frame, cig_box, pbox)

                    score  = 2                            # cigarette present
                    score += 2 if tip_found   else 0     # lit tip
                    score += 2 if smoke_found else 0     # smoke plume

                    if score >= 6:
                        candidate = "smoking_confirmed"
                    elif score >= 4:
                        candidate = "smoking_likely"
                    elif score >= 2:
                        candidate = "holding"
                    else:
                        candidate = "clear"

                    if STATUS_PRIORITY.get(candidate, 0) > STATUS_PRIORITY.get(best_status, 0):
                        best_status  = candidate
                        best_signals = {
                            "person_box": pbox.tolist(),
                            "cig_box":    cig_box.tolist() if hasattr(cig_box, "tolist") else list(cig_box),
                            "cig":        True,
                            "tip":        tip_found,
                            "tip_ratio":  tip_ratio,
                            "smoke":      smoke_found,
                            "smoke_area": smoke_area,
                            "score":      score,
                        }

                # temporal smoothing
                smoothed = self.smoother.smooth(person_id, best_status)
                person_statuses.append((person_id, smoothed, best_signals))

                frame_records.append({
                    "timestamp":  round(timestamp, 3),
                    "person_id":  person_id,
                    "status":     smoothed,
                    "raw_status": best_status,
                    "signals":    best_signals,
                })

        annotated = draw_smoking_overlay(frame, person_statuses, timestamp)
        return annotated, frame_records

    # ── public API ───────────────────────────────────────────────────────────

    def analyse_video(
        self,
        video_path:  str,
        output_dir:  Path,
        interval:    float = 0.5,
        save_frames: bool  = True,
        save_video:  bool  = True,
        video_fps:   float = 10.0,
        verbose:     bool  = True,
    ) -> list[dict]:
        """
        Analyse a video file for smoking detection.

        Parameters
        ----------
        video_path  : Path to the input video file.
        output_dir  : Directory where annotated frames and the output video are written.
        interval    : Sample one frame every `interval` seconds (default 0.5).
        save_frames : Save annotated JPEG for each non-clear event frame.
        save_video  : Write an annotated output MP4.
        video_fps   : FPS of the output video.
        verbose     : Print per-frame status to stdout.

        Returns
        -------
        list[dict]  — one dict per detected non-clear event (see module docstring).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        frames_dir = output_dir / "frames"
        footage_dir = output_dir / "footage"

        if save_frames:
            frames_dir.mkdir(parents=True, exist_ok=True)
        if save_video:
            footage_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"[SmokingDetector] Cannot open video: {video_path}")

        src_fps        = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_interval = max(1, int(src_fps * interval))
        src_w          = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h          = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if verbose:
            print(
                f"[SmokingDetector] Source: {video_path}\n"
                f"                  FPS={src_fps:.1f}  interval={interval}s → every {frame_interval} frames\n"
                f"                  Resolution: {src_w}×{src_h}"
            )

        video_out_path = footage_dir / "smoking_detection.mp4"
        writer: cv2.VideoWriter | None = None
        all_results: list[dict] = []
        frame_count  = 0
        saved_frames = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % frame_interval != 0:
                frame_count += 1
                continue

            timestamp          = frame_count / src_fps
            annotated, records = self._analyse_frame(frame, timestamp)
            any_event          = any(r["status"] != "clear" for r in records)

            if any_event:
                if save_frames:
                    fname = frames_dir / f"smoke_{timestamp:.3f}s.jpg"
                    cv2.imwrite(str(fname), annotated)
                    saved_frames += 1

                if save_video:
                    if writer is None:
                        ann_h, ann_w = annotated.shape[:2]
                        # Use avc1 (H.264) for browser compatibility, fallback to mp4v
                        fourcc_code = "avc1"
                        fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
                        test_writer = cv2.VideoWriter(
                            str(video_out_path), fourcc, video_fps, (ann_w, ann_h)
                        )
                        if not test_writer.isOpened():
                            fourcc_code = "mp4v"
                            fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
                            writer = cv2.VideoWriter(
                                str(video_out_path), fourcc, video_fps, (ann_w, ann_h)
                            )
                        else:
                            test_writer.release()
                            writer = cv2.VideoWriter(
                                str(video_out_path), fourcc, video_fps, (ann_w, ann_h)
                            )
                    writer.write(annotated)

                all_results.extend(records)

                if verbose:
                    for rec in records:
                        sig = rec["signals"]
                        print(
                            f"   t={timestamp:6.2f}s  P{rec['person_id']}  "
                            f"{rec['status']:<20}  "
                            f"cig={sig.get('cig', False)}  "
                            f"tip={sig.get('tip', False)}  "
                            f"smoke={sig.get('smoke', False)}"
                        )
            elif verbose:
                print(f"   t={timestamp:6.2f}s  (clear)")

            frame_count += 1

        cap.release()
        if writer:
            writer.release()
            if verbose:
                print(f"[SmokingDetector] Video  → {video_out_path}")

        if verbose:
            print(f"[SmokingDetector] Frames → {saved_frames} JPEGs in {output_dir}")
            print("[SmokingDetector] Done.")

        return all_results


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point — for standalone testing outside the FastAPI context
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    from collections import Counter as _Counter

    parser = argparse.ArgumentParser(description="Smoking Detection CLI")
    parser.add_argument("video",       help="Path to input video file")
    parser.add_argument("--person-model", default=MODEL_PATHS["person"],     help="Person detector weights")
    parser.add_argument("--cig-model",    default=MODEL_PATHS["cigarette"],  help="Cigarette detector weights (optional)")
    parser.add_argument("--interval",     type=float, default=1.0,            help="Sampling interval in seconds")
    parser.add_argument("--output-dir",   default=MODEL_PATHS["output_dir"], help="Where to save output video and frames")
    args = parser.parse_args()

    detector = SmokingDetector(
        person_model_path=args.person_model,
        cig_model_path=args.cig_model,
    )

    results = detector.analyse_video(
        video_path=args.video,
        output_dir=Path(args.output_dir),
        interval=args.interval,
        save_frames=True,
        save_video=True,
        video_fps=10.0,
        verbose=True,
    )

    # ── summary ──────────────────────────────────────────────────────────────
    status_count: _Counter = _Counter(r["status"] for r in results)
    print("\n📊 Summary:")
    for s, c in status_count.most_common():
        print(f"   {s:<22} → {c} occurrences")
    print(f"\nTotal events: {len(results)}")
