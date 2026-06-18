import time
import threading
import state as S
from state import frame_lock
from helpers import (
    run_roboflow_detection, set_detection_state,
    log_event
)
from config import (
    ROBOFLOW_ENABLED, ROBOFLOW_DETECTION_INTERVAL,
    STEPPER_ROTATIONS, STEPPER_ROTATION_DELAY
)

# Must import after helpers since run_roboflow_detection lives there
try:
    import requests
except ImportError:
    requests = None

try:
    import cv2
except ImportError:
    cv2 = None

CRAYFISH_COOLDOWN = 60


def trigger_stepper_rotations(count=STEPPER_ROTATIONS, delay=STEPPER_ROTATION_DELAY):
    from serial_monitor import send_serial_command

    def _run():
        for i in range(count):
            success = send_serial_command("STEPPER_ROTATE")
            print(f"[STEPPER] Rotation {i + 1}/{count} sent — {'OK' if success else 'FAILED'}")
            log_event("control", f"Stepper rotation {i + 1}/{count}", "STEPPER_ROTATE command sent")
            if i < count - 1:
                time.sleep(delay)

    threading.Thread(target=_run, daemon=True).start()


def detection_worker():
    if not ROBOFLOW_ENABLED:
        set_detection_state(
            enabled=False,
            last_error="ROBOFLOW_API_KEY or ROBOFLOW_MODEL_ID is missing",
            updated_at=time.time(),
        )
        return

    set_detection_state(enabled=True, last_error=None, updated_at=time.time())
    last_detection_time = 0

    while True:
        frame = None
        now = time.time()

        if (now - last_detection_time) >= ROBOFLOW_DETECTION_INTERVAL:
            with frame_lock:
                if S.latest_raw_frame is not None:
                    frame = S.latest_raw_frame.copy()

        if frame is None:
            time.sleep(0.1)
            continue

        started = time.time()
        try:
            detections = run_roboflow_detection(frame)

            if len(detections) > 0:
                current_time = time.time()
                if current_time - S.last_crayfish_detection > CRAYFISH_COOLDOWN:
                    print(f"[DETECTION] Crayfish detected! Triggering {STEPPER_ROTATIONS} stepper rotation(s).")
                    log_event("detection", "Crayfish detected",
                              f"{len(detections)} crayfish — rotating stepper x{STEPPER_ROTATIONS}")
                    trigger_stepper_rotations(count=STEPPER_ROTATIONS, delay=STEPPER_ROTATION_DELAY)
                    S.last_crayfish_detection = current_time

            latency_ms = int((time.time() - started) * 1000)
            set_detection_state(
                count=len(detections),
                detections=detections,
                last_latency_ms=latency_ms,
                last_success_at=time.time(),
                last_error=None,
                updated_at=time.time(),
            )
            last_detection_time = time.time()

        except Exception as e:
            set_detection_state(last_error=str(e), updated_at=time.time())
            last_detection_time = time.time()

        remaining = ROBOFLOW_DETECTION_INTERVAL - (time.time() - started)
        time.sleep(max(0.1, remaining))


