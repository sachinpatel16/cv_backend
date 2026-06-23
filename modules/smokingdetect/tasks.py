import os
import uuid
from pathlib import Path

from workers.celery import celery_app
from database.session import SessionLocal
from modules.smokingdetect.model import SmokingSession
from modules.smokingdetect.repository import SmokingDetectRepository
from workers.utils import run_async

# Storage directory for smoking detection results
SMOKING_DETECTION_DIR = os.path.join("storage", "smoking_detection")
os.makedirs(SMOKING_DETECTION_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Status severity ordering for determining overall_status
# ---------------------------------------------------------------------------
STATUS_SEVERITY = {
    "clear": 0,
    "holding": 1,
    "smoking_likely": 2,
    "smoking_confirmed": 3,
}


def _highest_severity(statuses: list[str]) -> str:
    """Return the most severe smoking status seen across all events."""
    if not statuses:
        return "clear"
    return max(statuses, key=lambda s: STATUS_SEVERITY.get(s, 0))


@celery_app.task(name="modules.smokingdetect.tasks.run_smoking_analysis")
def run_smoking_analysis(session_id_str: str, video_path: str, interval: float = 1.0):
    """
    Celery background task that runs smoking detection on the supplied video.

    Workflow:
      1. Mark session → 'processing'
      2. Run SmokingDetector.analyse_video()
      3. Persist each detected event as a SmokingEvent row
      4. Derive overall_status (worst severity across all events)
      5. Mark session → 'completed' with overall_status + video_out_path
      6. On any exception → mark session → 'failed'
    """
    session_id = uuid.UUID(session_id_str)

    async def run():
        async with SessionLocal() as db:
            repo = SmokingDetectRepository(db)

            # 1. Mark as processing ----------------------------------------
            await repo.update_session_status(session_id, "processing")
            await db.commit()

            try:
                # Validate the input video still exists on disk
                if not os.path.exists(video_path):
                    raise FileNotFoundError(
                        f"Input video not found on disk: {video_path}"
                    )

                # 2. Run AI analysis ----------------------------------------
                from modules.smokingdetect.service import smoking_detector  # type: ignore

                if smoking_detector is None:
                    raise RuntimeError(
                        "SmokingDetector was not loaded. Check model paths."
                    )

                output_dir = Path(SMOKING_DETECTION_DIR) / session_id_str
                output_dir.mkdir(parents=True, exist_ok=True)

                results: list[dict] = smoking_detector.analyse_video(
                    video_path=video_path,
                    output_dir=output_dir,
                    interval=interval,
                    save_frames=True,
                    save_video=True,
                    video_fps=10.0,
                    verbose=False,
                )

                # 3. Persist events -----------------------------------------
                all_statuses: list[str] = []

                for result in results:
                    # Build the frame path for this event
                    ts = result.get("timestamp", 0.0)
                    frame_filename = f"smoke_{ts:.3f}s.jpg"
                    frame_path = os.path.join(
                        SMOKING_DETECTION_DIR,
                        session_id_str,
                        "frames",
                        frame_filename,
                    )
                    frame_path_posix = Path(frame_path).as_posix()

                    # Attach frame_path into the dict so repository can store it
                    result["frame_path"] = frame_path_posix if os.path.exists(frame_path) else None

                    await repo.create_event(session_id, result)
                    all_statuses.append(result.get("status", "clear"))

                await db.commit()

                # 4. Determine overall_status --------------------------------
                overall_status = _highest_severity(all_statuses)

                # 5. Locate the annotated output video ----------------------
                # SmokingDetector saves video into output_dir / "footage"; find the first .mp4
                video_out_path: str | None = None
                footage_dir = output_dir / "footage"
                if footage_dir.exists():
                    for fname in os.listdir(footage_dir):
                        if fname.endswith(".mp4") or fname.endswith(".avi"):
                            raw_out_path = Path(footage_dir / fname)
                            h264_out_path = footage_dir / "smoking_detection_h264.mp4"
                            
                            # Attempt to re-encode it to browser-compatible H.264 using ffmpeg
                            import subprocess
                            try:
                                print(f"[SmokingDetect] Re-encoding {raw_out_path} to H.264 using ffmpeg...")
                                cmd = [
                                    "ffmpeg",
                                    "-y",
                                    "-i", str(raw_out_path),
                                    "-vcodec", "libx264",
                                    "-pix_fmt", "yuv420p",
                                    "-profile:v", "baseline",
                                    "-level", "3.0",
                                    str(h264_out_path)
                                ]
                                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                                # Replace the raw file with the H264 file
                                raw_out_path.unlink(missing_ok=True)
                                h264_out_path.rename(raw_out_path)
                                print(f"[SmokingDetect] Re-encoding successful.")
                            except Exception as e:
                                print(f"[SmokingDetect] ffmpeg re-encoding failed: {e}. Keeping raw output.")
                                if h264_out_path.exists():
                                    h264_out_path.unlink(missing_ok=True)

                            video_out_path = raw_out_path.as_posix()
                            break

                # 6. Mark session completed ---------------------------------
                await repo.update_session_status(
                    session_id,
                    status="completed",
                    overall_status=overall_status,
                    video_out_path=video_out_path,
                )
                await db.commit()

                print(
                    f"[SmokingDetect] Session {session_id_str} completed. "
                    f"Events: {len(results)}, Overall: {overall_status}"
                )

            except Exception as exc:
                print(f"[SmokingDetect] Session {session_id_str} FAILED: {exc}")
                await repo.update_session_status(session_id, "failed")
                await db.commit()

    run_async(run())
