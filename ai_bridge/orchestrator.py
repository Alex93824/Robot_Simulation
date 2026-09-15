"""
orchestrator.py
----------------
Fully autonomous robot agent.

Nemotron-120B is the high-level autonomous brain.
Qwen3-VL (via VisionWorker) is the visual perception system.
Webots is the physical simulation.

Architecture:
    Main thread:   Nemotron agent loop  (observe → think → act, forever)
    Daemon thread: VisionWorker         (latest-frame capture + Qwen3-VL)

The loop runs until the operator presses Ctrl+C, Webots disconnects,
or an unrecoverable API failure occurs.  There is no turn limit.

Usage:
    python orchestrator.py "Explore the environment autonomously."
    python orchestrator.py "Find a red object and investigate it."

Setup:
    pip install openai python-dotenv
    Set NVIDIA_API_KEY in ai_bridge/.env
    Start llama-server for Qwen3-VL  (see VISION_SERVER_SETUP.md)
    Open Webots world and press Play so the controller is running.
"""

import os
import sys
import json
import time
import atexit
import signal
import threading
from collections import deque

from dotenv import load_dotenv
from openai import OpenAI

from webots_client import WebotsClient
from vision_client import VisionWorker

load_dotenv()

# ── NVIDIA / model config ──────────────────────────────────────────────────────
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
if not NVIDIA_API_KEY:
    print("ERROR: NVIDIA_API_KEY not found. Add it to ai_bridge/.env")
    sys.exit(1)

MODEL_NAME = "nvidia/nemotron-3-super-120b-a12b"
# To swap models if needed:
#   nvidia/nemotron-3-super-120b-a12b   ← default (strong tool-calling)
#   nvidia/nemotron-3-ultra-550b-a55b   ← larger, slower
#   nvidia/nemotron-3.5-lightning-30b-a3b ← faster, smaller
# Browse https://build.nvidia.com for current availability.

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

# ── Configurable constants ─────────────────────────────────────────────────────
MAX_CONTEXT_MESSAGES  = 20      # max conversation messages kept (excl. system)
MAX_ACTION_HISTORY    = 10      # recent actions shown in system prompt
MAX_SPEED             = 1.0     # hard speed cap  (fraction of max)
MAX_DURATION          = 10.0    # hard duration cap (seconds)
MIN_DURATION          = 0.1     # minimum duration floor (seconds)
NVIDIA_RETRY_ATTEMPTS = 3       # how many times to retry a failed API call
NVIDIA_RETRY_BACKOFF  = 5.0     # initial retry delay (seconds); doubles each retry
MAX_CONSECUTIVE_TEXT  = 3       # threshold before a stronger continuation nudge
# ─────────────────────────────────────────────────────────────────────────────


# ── Tool definitions (OpenAI tool-calling format) ──────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move_forward",
            "description": (
                "Drive the robot straight forward or backward for a given duration. "
                "Prefer short steps (1–3 seconds) and re-observe with describe_camera "
                "frequently rather than long blind movements."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["forward", "backward"],
                        "description": "Direction to move.",
                    },
                    "speed": {
                        "type": "number",
                        "description": "Speed as a fraction of max speed, 0.0–1.0. Default 0.5.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "duration": {
                        "type": "number",
                        "description": "How long to move, in seconds (max 10 s). Use 1–3 s normally.",
                    },
                },
                "required": ["direction", "speed", "duration"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "turn",
            "description": (
                "Rotate the robot in place left or right for a given duration. "
                "Use 0.3–0.8 s turns to adjust heading, up to ~2 s for larger turns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["left", "right"],
                        "description": "Turn direction.",
                    },
                    "speed": {
                        "type": "number",
                        "description": "Turn speed fraction 0.0–1.0. Default 0.5.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "duration": {
                        "type": "number",
                        "description": "How long to turn, in seconds (max 10 s).",
                    },
                },
                "required": ["direction", "speed", "duration"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop",
            "description": "Immediately stop all robot movement.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_camera",
            "description": (
                "Capture the robot's current camera frame and analyse it with the "
                "visual AI using your specific question.\n\n"
                "ALWAYS provide a targeted question — never a generic request.\n"
                "Good examples:\n"
                "  - 'Is the path directly ahead clear of obstacles?'\n"
                "  - 'What objects are visible on the left side and how far away?'\n"
                "  - 'Is there a wall or barrier ahead? How close?'\n"
                "  - 'Is there anything red or unusual in the scene?'\n"
                "  - 'Can the robot safely continue forward?'\n"
                "  - 'What is the overall layout: open space, corridor, room?'\n\n"
                "This is your primary perception tool. Use it before moving in any "
                "unfamiliar direction or when you need to make a navigation decision."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "Your targeted visual question for this moment. "
                            "The vision AI will answer exactly this. Be specific."
                        ),
                    }
                },
                "required": ["question"],
            },
        },
    },
]


# ── System prompt template ─────────────────────────────────────────────────────
_SYSTEM_TEMPLATE = """\
You are the fully autonomous brain of a Pioneer3-AT mobile robot in a Webots \
simulation. You operate in a continuous OBSERVE → THINK → ACT loop with no \
fixed endpoint. Your mission continues until the human operator manually stops \
the system.

══════════════════════════════════════════════════════
YOUR CURRENT MISSION:
{mission}
══════════════════════════════════════════════════════

CURRENT VISUAL OBSERVATION:
{current_observation}

──────────────────────────────────────────────────────
RECENT VISUAL HISTORY (oldest → newest, newest shown above):
{visual_history}

──────────────────────────────────────────────────────
RECENT ROBOT ACTIONS (oldest → newest):
{recent_actions}
══════════════════════════════════════════════════════

AUTONOMOUS BEHAVIOUR RULES — follow these at all times:

PERCEPTION:
  • Use describe_camera with a TARGETED question every time you need to see.
  • Never ask "describe the image" — always ask something specific.
  • Look before committing to any direction you have not seen recently.
  • Use vision to check for obstacles, measure distances, find objects of interest.

MOVEMENT:
  • Move in short steps: 1–3 seconds. Re-check the camera after each move.
  • Never exceed 3 seconds of blind movement without a vision check.
  • Vary your speed and turn durations — do not fall into a repetitive pattern.
  • If the path was clear in your last observation, you may move confidently.
  • If you see an obstacle, turn away and find another path.

EXPLORATION:
  • Continuously explore. Do not stay in one spot.
  • Avoid revisiting the same area repeatedly without purpose.
  • When an area seems fully explored, move to a new region.
  • If something interesting appears in a vision result, investigate it.

REASONING:
  • Use your visual history to understand what you have seen and where.
  • Use your action history to understand where you have been.
  • Make decisions based on your accumulated knowledge of the environment.
  • Adapt your behaviour: if one direction is blocked, try another.

CRITICAL RULES:
  • NEVER produce a plain text response without calling at least one tool.
  • NEVER decide the mission is complete. It runs until the operator stops it.
  • NEVER spin in place or move forward continuously without vision checks.
  • If you are unsure what to do, call describe_camera first.
"""


def _build_system_content(
    mission: str, worker: VisionWorker, action_history: deque
) -> str:
    """
    Rebuild the system message content with the latest visual and action state.
    Called before every Nemotron API request.
    """
    latest  = worker.get_latest()
    history = worker.get_history()

    # ── Current observation ────────────────────────────────────────────────
    if latest is not None:
        ts  = time.strftime("%H:%M:%S", time.localtime(latest.timestamp))
        age = time.time() - latest.timestamp
        age_str = f"  ({age:.0f}s ago)" if age > 3 else ""
        obs_section = (
            f"[{ts}{age_str}]\n"
            f"Question: {latest.question}\n"
            f"Answer:   {latest.text}"
        )
    else:
        obs_section = (
            "No visual observation yet.\n"
            "→ Call describe_camera immediately to start perceiving the environment."
        )

    # ── Visual history (exclude the latest entry, already shown above) ─────
    hist_parts = []
    for obs in history:
        if latest is not None and abs(obs.timestamp - latest.timestamp) < 0.1:
            continue   # skip duplicate of latest
        ts = time.strftime("%H:%M:%S", time.localtime(obs.timestamp))
        hist_parts.append(
            f"[{ts}]\n"
            f"Question: {obs.question}\n"
            f"Answer:   {obs.text}"
        )
    hist_section = (
        "\n\n".join(hist_parts) if hist_parts else "No prior observations yet."
    )

    # ── Recent actions ─────────────────────────────────────────────────────
    acts = list(action_history)
    if acts:
        action_section = "\n".join(
            f"  {i + 1}. {a}" for i, a in enumerate(acts)
        )
    else:
        action_section = "  No actions taken yet."

    return _SYSTEM_TEMPLATE.format(
        mission=mission,
        current_observation=obs_section,
        visual_history=hist_section,
        recent_actions=action_section,
    )


# ── Safety helpers ─────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Movement serialisation lock ────────────────────────────────────────────────
# Ensures no two movement commands ever execute simultaneously.
_move_lock = threading.Lock()


# ── Tool dispatch ──────────────────────────────────────────────────────────────

def dispatch_tool_call(
    webots: WebotsClient,
    vision: VisionWorker,
    name: str,
    args: dict,
    action_history: deque,
) -> str:
    """Execute one tool call. Returns a JSON string to feed back to Nemotron."""

    if name == "move_forward":
        direction = args.get("direction", "forward")
        speed     = _clamp(float(args.get("speed",    0.5)), 0.0, MAX_SPEED)
        duration  = _clamp(float(args.get("duration", 1.0)), MIN_DURATION, MAX_DURATION)
        sign      = 1.0 if direction == "forward" else -1.0

        print(f"[robot] Moving {direction}  speed={speed:.2f}  duration={duration:.1f}s")
        action_history.append(
            f"move_forward({direction}, speed={speed:.2f}, duration={duration:.1f}s)"
        )
        with _move_lock:
            result = webots.move(left=sign * speed, right=sign * speed, duration=duration)
        return json.dumps(result)

    elif name == "turn":
        direction = args.get("direction", "left")
        speed     = _clamp(float(args.get("speed",    0.5)), 0.0, MAX_SPEED)
        duration  = _clamp(float(args.get("duration", 1.0)), MIN_DURATION, MAX_DURATION)

        print(f"[robot] Turning {direction}  speed={speed:.2f}  duration={duration:.1f}s")
        action_history.append(
            f"turn({direction}, speed={speed:.2f}, duration={duration:.1f}s)"
        )
        with _move_lock:
            if direction == "left":
                result = webots.move(left=-speed, right=speed, duration=duration)
            else:
                result = webots.move(left=speed, right=-speed, duration=duration)
        return json.dumps(result)

    elif name == "stop":
        print("[robot] Stopping.")
        action_history.append("stop()")
        with _move_lock:
            result = webots.stop()
        return json.dumps(result)

    elif name == "describe_camera":
        question = args.get("question", "Describe the current scene for robot navigation.")
        # request_description() blocks until the VL inference completes.
        text = vision.request_description(question)
        return json.dumps({"description": text})

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


# ── NVIDIA API call with exponential-backoff retry ─────────────────────────────

def call_nemotron(messages: list):
    """
    Call the Nemotron API.  Retries up to NVIDIA_RETRY_ATTEMPTS times on
    transient failures.  Raises RuntimeError after all attempts are exhausted.
    """
    backoff   = NVIDIA_RETRY_BACKOFF
    last_exc  = None

    for attempt in range(1, NVIDIA_RETRY_ATTEMPTS + 1):
        try:
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.4,
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"[agent] NVIDIA API error (attempt {attempt}/{NVIDIA_RETRY_ATTEMPTS}): {exc}"
            )
            if attempt < NVIDIA_RETRY_ATTEMPTS:
                print(f"[agent] Retrying in {backoff:.0f}s ...")
                time.sleep(backoff)
                backoff *= 2.0

    raise RuntimeError(
        f"NVIDIA API failed after {NVIDIA_RETRY_ATTEMPTS} attempts: {last_exc}"
    )


# ── Rolling message-window management ─────────────────────────────────────────

def trim_messages(messages: list) -> None:
    """
    Keep messages[0] (system) plus the last MAX_CONTEXT_MESSAGES conversation
    items.  After trimming, ensure the oldest kept message is not an orphaned
    tool result (which would cause an API error because its tool_call_id
    would reference a dropped assistant message).
    """
    if len(messages) <= 1 + MAX_CONTEXT_MESSAGES:
        return

    system = messages[:1]
    rest   = messages[-(MAX_CONTEXT_MESSAGES):]

    # Drop leading orphan tool-result messages
    while rest and rest[0].get("role") == "tool":
        rest = rest[1:]

    messages.clear()
    messages.extend(system + rest)


# ── Emergency shutdown infrastructure ─────────────────────────────────────────

_webots_ref: WebotsClient = None
_vision_ref: VisionWorker = None


def _emergency_stop() -> None:
    """Called by atexit and SIGINT.  Best-effort — never raises."""
    global _webots_ref, _vision_ref
    print("\n[robot] Emergency stop.")
    try:
        if _vision_ref is not None:
            _vision_ref.stop()
    except Exception:
        pass
    try:
        if _webots_ref is not None:
            _webots_ref.stop()
    except Exception:
        pass
    try:
        if _webots_ref is not None:
            _webots_ref.close()
    except Exception:
        pass


atexit.register(_emergency_stop)


def _sigint_handler(sig, frame) -> None:
    print("\n[agent] Ctrl+C — stopping robot and exiting.")
    _emergency_stop()
    # Use os._exit to avoid atexit running a second time in some edge cases
    # but we registered _emergency_stop as atexit so it's fine either way.
    sys.exit(0)


signal.signal(signal.SIGINT, _sigint_handler)


# ── Main autonomous agent loop ────────────────────────────────────────────────

def run_agent(mission: str) -> None:
    global _webots_ref, _vision_ref

    print(f"[agent] Connecting to Webots ...")
    try:
        webots = WebotsClient()
    except Exception as exc:
        print(f"[agent] Cannot connect to Webots: {exc}")
        print("[agent] Make sure Webots is running and the simulation has started.")
        sys.exit(1)

    _webots_ref = webots
    print("[agent] Connected to Webots.")

    vision = VisionWorker(webots)
    _vision_ref = vision
    vision.start()

    # Rolling action history (bounded deque)
    action_history: deque = deque(maxlen=MAX_ACTION_HISTORY)

    # Build initial messages list.
    # messages[0] is the system message — rebuilt before every API call.
    messages = [
        {
            "role": "system",
            "content": _build_system_content(mission, vision, action_history),
        },
        {
            "role": "user",
            "content": (
                f"Mission activated: {mission}\n\n"
                "Start by looking at your surroundings with describe_camera, "
                "then begin exploring. Do not stop."
            ),
        },
    ]

    consecutive_text_only = 0
    loop_count            = 0

    print(f"\n[agent] Mission: {mission}")
    print("[agent] Autonomous loop started. Press Ctrl+C to stop.\n")
    print("─" * 60)

    try:
        while True:
            loop_count += 1

            # Rebuild system message with latest visual + action context
            messages[0]["content"] = _build_system_content(
                mission, vision, action_history
            )

            print(f"\n[agent] Thinking...  (cycle #{loop_count})")

            # ── Call Nemotron ──────────────────────────────────────────────
            try:
                response = call_nemotron(messages)
            except RuntimeError as exc:
                print(f"[agent] FATAL API failure: {exc}")
                break

            msg      = response.choices[0].message
            msg_dict = msg.model_dump(exclude_none=True)
            messages.append(msg_dict)

            # ── Nemotron made tool calls ───────────────────────────────────
            if msg.tool_calls:
                consecutive_text_only = 0

                for tool_call in msg.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    print(f"[tool call] {fn_name}({fn_args})")
                    result_str = dispatch_tool_call(
                        webots, vision, fn_name, fn_args, action_history
                    )
                    preview = result_str[:200]
                    print(f"[tool result] {preview}")

                    messages.append(
                        {
                            "role":        "tool",
                            "tool_call_id": tool_call.id,
                            "content":     result_str,
                        }
                    )

            # ── Nemotron gave a text-only response (no tool calls) ─────────
            else:
                consecutive_text_only += 1

                if msg.content:
                    print(f"[agent] (text) {msg.content[:300]}")

                # Mission is active — inject a continuation prompt.
                # Use a stronger nudge if this keeps repeating.
                if consecutive_text_only >= MAX_CONSECUTIVE_TEXT:
                    print(
                        f"[agent] WARNING: {consecutive_text_only} consecutive "
                        "text-only responses.  Sending strong continuation directive."
                    )
                    consecutive_text_only = 0
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "DIRECTIVE: You have responded with text multiple times "
                                "without calling any tools. This is not acceptable. "
                                f"Your mission '{mission}' is ACTIVE and must continue. "
                                "You MUST call describe_camera or a movement tool RIGHT NOW. "
                                "Do not write any text. Only call a tool."
                            ),
                        }
                    )
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Mission is still active. Continue exploring. "
                                "Call describe_camera or a movement tool now."
                            ),
                        }
                    )

            # Trim old messages to keep the context window bounded
            trim_messages(messages)

    except KeyboardInterrupt:
        print("\n[agent] KeyboardInterrupt received.")

    except ConnectionError as exc:
        print(f"\n[agent] Webots connection lost: {exc}")

    except Exception as exc:
        print(f"\n[agent] Unexpected error: {exc}")
        raise

    finally:
        print("\n[agent] Shutting down ...")
        try:
            vision.stop()
        except Exception:
            pass
        try:
            webots.stop()
        except Exception:
            pass
        try:
            webots.close()
        except Exception:
            pass
        print("[agent] Shutdown complete.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage:   python orchestrator.py "mission description"')
        print('Example: python orchestrator.py "Explore the environment autonomously."')
        print('Example: python orchestrator.py "Find a red object."')
        sys.exit(1)

    mission_text = " ".join(sys.argv[1:])
    run_agent(mission_text)