"""
vision_client.py
-----------------
Continuous latest-frame vision worker for the autonomous robot.

Architecture:
    Webots camera
        ↓
    latest-frame buffer  (one slot — newest frame overwrites old)
        ↓
    single VL worker thread  (NEVER concurrent — 1 GTX 1650 GPU)
        ↓
    latest completed observation + bounded history
        ↓
    Nemotron

Inference is driven by Nemotron priority requests.
An optional background pass runs only when no priority request is pending
and the inference slot is free.  Stale frames are dropped before processing.

GTX 1650 / 4 GB VRAM constraints:
  • At most ONE Qwen3-VL inference runs at any time.
  • No queue — only the newest frame is ever processed.
  • Background captures are rate-limited and skipped when GPU is busy.
"""

import threading
import time
import requests
from collections import deque
from dataclasses import dataclass
from typing import Optional

# ── Configurable constants ────────────────────────────────────────────────────
VISION_SERVER_URL       = "http://127.0.0.1:8090/v1/chat/completions"
VISION_TIMEOUT_SECONDS  = 25      # HTTP timeout for one inference call
VISION_HISTORY_SIZE     = 8       # max observations kept in rolling history
BACKGROUND_INTERVAL     = 8.0     # seconds between autonomous background captures
                                  #   set to 0 to disable background captures entirely
FRAME_STALE_TIMEOUT     = 20.0    # drop a buffered frame older than this (seconds)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Observation:
    """One completed VL inference result."""
    timestamp: float   # wall-clock time of completion
    question:  str     # exact question sent to the VL model
    text:      str     # VL model answer


class VisionWorker:
    """
    Background daemon thread that:
      1. Accepts priority requests from Nemotron via request_description().
      2. Optionally performs background observations at BACKGROUND_INTERVAL.
      3. Guarantees at most ONE concurrent Qwen3-VL inference (serialised via
         self._inference_lock).
      4. Keeps a bounded rolling history of Observation objects.

    Usage:
        worker = VisionWorker(webots_client)
        worker.start()

        # Nemotron calls this (blocks until VL is done):
        text = worker.request_description("Is the path ahead clear?")

        # Read back state:
        latest = worker.get_latest()   # Observation | None
        history = worker.get_history() # list[Observation]

        worker.stop()
    """

    def __init__(self, webots_client):
        self._webots = webots_client

        # ── Latest raw-frame buffer (one slot, newest frame always wins) ──────
        self._frame_lock   = threading.Lock()
        self._latest_frame: Optional[str]   = None   # base64 JPEG string
        self._frame_time:   Optional[float] = None   # wall-clock time of capture

        # ── Priority request state (set by Nemotron via request_description) ──
        self._priority_lock          = threading.Lock()
        self._priority_event         = threading.Event()   # signals a new request
        self._priority_question:     Optional[str] = None
        self._priority_result:       Optional[Observation] = None
        self._priority_result_event  = threading.Event()   # signals completion

        # ── VL inference serialisation gate ──────────────────────────────────
        # Only one thread may hold this lock while running _call_vision_server.
        self._inference_lock = threading.Lock()

        # ── Observation store ─────────────────────────────────────────────────
        self._obs_lock   = threading.Lock()
        self._latest_obs: Optional[Observation] = None
        self._history: deque = deque(maxlen=VISION_HISTORY_SIZE)

        # ── Worker control ────────────────────────────────────────────────────
        self._stop_event = threading.Event()
        self._thread     = threading.Thread(
            target=self._run, daemon=True, name="VisionWorker"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background worker thread."""
        self._thread.start()
        print("[vision] Worker started.")

    def stop(self) -> None:
        """Signal the worker to stop and wait for it."""
        self._stop_event.set()
        self._priority_event.set()   # unblock wait() if sleeping
        self._thread.join(timeout=5.0)
        print("[vision] Worker stopped.")

    def request_description(self, question: str) -> str:
        """
        Called by Nemotron (from the main agent thread) when it needs a
        visual answer to a specific question.

        Behaviour:
          • Signals the worker thread to capture the freshest possible frame.
          • Passes the exact question to Qwen3-VL (no rewriting).
          • Blocks until the inference completes (or times out).
          • Stores the result in history.
          • Returns the VL model's answer as a string.

        This call is always serialised — there is never more than one
        concurrent inference running.
        """
        print(f"[vision] Priority request: {question[:100]}")

        with self._priority_lock:
            self._priority_question = question
            self._priority_result   = None
            self._priority_result_event.clear()
            self._priority_event.set()          # wake the worker

        # Block until the worker signals completion
        timeout = VISION_TIMEOUT_SECONDS + 10
        finished = self._priority_result_event.wait(timeout=timeout)

        if not finished:
            return "[vision error] Timed out waiting for VL inference result."

        with self._priority_lock:
            obs = self._priority_result

        if obs is None:
            return "[vision error] Worker returned no result."
        return obs.text

    def get_latest(self) -> Optional[Observation]:
        """Return the most recently completed Observation (thread-safe)."""
        with self._obs_lock:
            return self._latest_obs

    def get_history(self) -> list:
        """Return a copy of the recent observation history (thread-safe)."""
        with self._obs_lock:
            return list(self._history)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _capture_frame(self) -> Optional[str]:
        """
        Grab a fresh frame from Webots and update the internal buffer.
        Returns the base64 JPEG string or None on failure.
        """
        try:
            result = self._webots.get_camera()
            if result.get("ok", True) and "image_b64" in result:
                img = result["image_b64"]
                with self._frame_lock:
                    self._latest_frame = img
                    self._frame_time   = time.time()
                print("[vision] Captured frame.")
                return img
            else:
                print(f"[vision] Camera capture failed: {result}")
                return None
        except Exception as e:
            print(f"[vision] Frame capture error: {e}")
            return None

    def _get_buffered_frame(self) -> Optional[str]:
        """
        Return the buffered frame if it is fresh enough, otherwise drop it.
        """
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            age = time.time() - self._frame_time
            if age > FRAME_STALE_TIMEOUT:
                print(f"[vision] Buffered frame is stale ({age:.1f}s old). Discarding.")
                self._latest_frame = None
                self._frame_time   = None
                return None
            return self._latest_frame

    def _run_inference(self, image_b64: str, question: str) -> str:
        """
        Run one VL inference.  Holds _inference_lock for its entire duration.
        This is the single serialisation point that prevents concurrent GPU use.
        """
        print(f"[vision] Processing frame...")
        print(f"[vision] Question: {question[:120]}")
        with self._inference_lock:
            return _call_vision_server(image_b64, question)

    def _store_observation(self, question: str, text: str) -> Observation:
        """Create an Observation, store it as latest and append to history."""
        obs = Observation(timestamp=time.time(), question=question, text=text)
        with self._obs_lock:
            self._latest_obs = obs
            self._history.append(obs)
        print(f"[vision] Result: {text[:140]}")
        return obs

    # ── Worker main loop ───────────────────────────────────────────────────────

    def _run(self) -> None:
        last_background_time: float = 0.0

        while not self._stop_event.is_set():

            # ── 1. Priority request from Nemotron (highest precedence) ────────
            signalled = self._priority_event.wait(timeout=1.0)

            if self._stop_event.is_set():
                break

            if signalled:
                self._priority_event.clear()

                with self._priority_lock:
                    question = self._priority_question

                if question is None:
                    continue

                # Always try to get the very latest frame for a priority request
                img = self._capture_frame()
                if img is None:
                    # Fall back to the buffer if capture failed
                    img = self._get_buffered_frame()

                if img is None:
                    err_obs = Observation(
                        timestamp=time.time(),
                        question=question,
                        text="[vision error] Could not capture a camera frame from Webots.",
                    )
                    with self._priority_lock:
                        self._priority_result = err_obs
                    self._priority_result_event.set()
                    continue

                text = self._run_inference(img, question)
                obs  = self._store_observation(question, text)
                last_background_time = time.time()   # reset background timer

                with self._priority_lock:
                    self._priority_result = obs
                self._priority_result_event.set()
                continue

            # ── 2. Optional background observation ────────────────────────────
            # Only runs when: background enabled, interval elapsed, no priority
            # pending, and inference slot is free.
            if BACKGROUND_INTERVAL <= 0:
                continue

            now = time.time()
            if now - last_background_time < BACKGROUND_INTERVAL:
                continue

            # Do not start a background capture if the GPU is busy
            if self._inference_lock.locked():
                continue

            img = self._capture_frame()
            if img is None:
                last_background_time = time.time()
                continue

            bg_question = (
                "You are the vision system of a mobile robot exploring an "
                "environment. Describe what you see ahead: obstacles, open paths, "
                "walls, or objects of interest. Be concise (2-3 sentences). "
                "Mention direction (left/right/center) and rough distance."
            )
            text = self._run_inference(img, bg_question)
            self._store_observation(bg_question, text)
            last_background_time = time.time()


# ── Low-level HTTP helper ──────────────────────────────────────────────────────

def _call_vision_server(image_b64: str, question: str) -> str:
    """
    POST one image + question to llama-server and return the text answer.
    Never raises — returns an error string on failure.
    """
    payload = {
        "model": "qwen3-vl",   # llama-server ignores the exact value but requires the field
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 220,
        "temperature": 0.1,
    }
    try:
        resp = requests.post(
            VISION_SERVER_URL, json=payload, timeout=VISION_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return (
            f"[vision error] Cannot reach vision server at {VISION_SERVER_URL}. "
            "Is llama-server running?"
        )
    except requests.exceptions.Timeout:
        return "[vision error] Vision server timed out."
    except Exception as e:
        return f"[vision error] {e}"


# ── Backward-compatible standalone helper ──────────────────────────────────────

def describe_image(image_b64: str, question: str = None) -> str:
    """
    Synchronous single-shot image description.
    Preserved for backward compatibility and standalone testing.
    """
    if question is None:
        question = (
            "You are the vision system of a mobile robot. Describe what is "
            "directly in front of the robot: obstacles, open paths, walls, "
            "people, or objects of interest. Be concise (2-3 sentences) and "
            "specific about direction (left/right/center) and rough distance."
        )
    return _call_vision_server(image_b64, question)


if __name__ == "__main__":
    import sys
    import base64

    if len(sys.argv) < 2:
        print("Usage: python vision_client.py <path_to_image.jpg> [question]")
        sys.exit(1)

    with open(sys.argv[1], "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")

    q = sys.argv[2] if len(sys.argv) > 2 else None
    print(describe_image(b64, q))
