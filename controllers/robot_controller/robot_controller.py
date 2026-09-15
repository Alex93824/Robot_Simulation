"""
robot_controller.py
--------------------
Webots controller for a Pioneer3-AT (4-wheel) robot + camera.

Set this as the "controller" field of your Robot node in Webots
(controller name must match this file's name without extension:
i.e. this file should live at controllers/robot_controller/robot_controller.py
and the Robot.controller field should be "robot_controller").

This controller does NOT decide anything by itself. It just:
  1. Steps the simulation.
  2. Opens a TCP server on localhost.
  3. Accepts one external client (your orchestrator.py) at a time.
  4. Executes simple JSON commands sent by that client:
       {"cmd": "move", "left": <float -1..1>, "right": <float -1..1>, "duration": <seconds>}
       {"cmd": "stop"}
       {"cmd": "get_camera"}      -> returns base64 JPEG of current camera frame
       {"cmd": "get_status"}      -> returns basic robot status
  5. Sends back a JSON response for every command.

Wheel speeds are expressed as a fraction of max velocity (-1.0 to 1.0),
where 1.0 = full speed forward, -1.0 = full speed backward.
Left/right values let the orchestrator do differential or skid steering:
  forward:      left=1,  right=1
  backward:     left=-1, right=-1
  turn left:    left=-1, right=1   (or left=0, right=1 for a gentler turn)
  turn right:   left=1,  right=-1
"""

import json
import socket
import base64
import threading
import time

from controller import Robot  # Webots API


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 10101

# Actual Pioneer3-AT motor device names (confirmed from the official PROTO)
WHEEL_NAMES = {
    "front_left": "front left wheel",
    "front_right": "front right wheel",
    "back_left": "back left wheel",
    "back_right": "back right wheel",
}

MAX_SPEED_FRACTION_DEFAULT = 0.5  # safety default: don't slam to full speed unless asked


# ----------------------------------------------------------------------
# Robot / device setup
# ----------------------------------------------------------------------
robot = Robot()
timestep = int(robot.getBasicTimeStep())

wheels = {}
for key, device_name in WHEEL_NAMES.items():
    motor = robot.getDevice(device_name)
    motor.setPosition(float("inf"))  # velocity control mode
    motor.setVelocity(0.0)
    wheels[key] = motor

max_wheel_velocity = wheels["front_left"].getMaxVelocity()

# Auto-detect the camera device: try common names first, then scan all devices.
camera = None
camera_candidates = ["camera", "Camera", "front_camera", "cam"]
for name in camera_candidates:
    try:
        candidate = robot.getDevice(name)
        if candidate is not None:
            camera = candidate
            break
    except Exception:
        continue

if camera is None:
    # Fall back: scan every device on the robot for one that behaves like a Camera
    for i in range(robot.getNumberOfDevices()):
        dev = robot.getDeviceByIndex(i)
        try:
            dev.getWidth()  # only Camera-like devices have this
            dev.getHeight()
            camera = dev
            break
        except Exception:
            continue

if camera is not None:
    camera.enable(timestep)
    print(f"[robot_controller] Camera enabled: {camera.getName()} "
          f"({camera.getWidth()}x{camera.getHeight()})")
else:
    print("[robot_controller] WARNING: no camera device found on the robot.")


# ----------------------------------------------------------------------
# Shared state between the Webots main loop and the socket server thread
# ----------------------------------------------------------------------
state_lock = threading.Lock()
pending_command = None       # dict, set by the socket thread, consumed by main loop
last_response = None         # dict, set by main loop, sent by socket thread
command_ready = threading.Event()
response_ready = threading.Event()

# Timed-motion bookkeeping (so "move for N seconds" doesn't block the socket thread)
move_end_time = [0.0]        # wall/sim time (seconds) at which motors should stop
stop_after_move = [False]


def set_wheel_speeds(left_fraction, right_fraction):
    """left_fraction / right_fraction are floats in [-1, 1]."""
    left_fraction = max(-1.0, min(1.0, left_fraction))
    right_fraction = max(-1.0, min(1.0, right_fraction))
    left_v = left_fraction * max_wheel_velocity
    right_v = right_fraction * max_wheel_velocity

    wheels["front_left"].setVelocity(left_v)
    wheels["back_left"].setVelocity(left_v)
    wheels["front_right"].setVelocity(right_v)
    wheels["back_right"].setVelocity(right_v)


def stop_all():
    set_wheel_speeds(0.0, 0.0)


def capture_camera_jpeg_b64():
    """Grab current camera frame and return it as base64-encoded JPEG bytes."""
    if camera is None:
        return None
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()  # raw BGRA bytes

    # Convert raw BGRA -> JPEG using Pillow (avoids needing OpenCV)
    from PIL import Image
    img = Image.frombytes("RGBA", (width, height), image, "raw", "BGRA")
    img = img.convert("RGB")

    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ----------------------------------------------------------------------
# Socket server (runs in a background thread)
# ----------------------------------------------------------------------
def handle_client(conn):
    global pending_command, last_response
    conn_file = conn.makefile("rwb")
    while True:
        line = conn_file.readline()
        if not line:
            break
        try:
            command = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            conn_file.write((json.dumps({"error": "invalid_json"}) + "\n").encode("utf-8"))
            conn_file.flush()
            continue

        with state_lock:
            pending_command = command
            command_ready.set()

        # Wait for the main Webots loop to process it and produce a response
        response_ready.wait(timeout=5.0)
        with state_lock:
            response = last_response
            response_ready.clear()

        if response is None:
            response = {"error": "timeout_waiting_for_main_loop"}

        conn_file.write((json.dumps(response) + "\n").encode("utf-8"))
        conn_file.flush()


def server_thread_fn():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"[robot_controller] Listening on {HOST}:{PORT} ...")
    while True:
        conn, addr = srv.accept()
        print(f"[robot_controller] Orchestrator connected from {addr}")
        try:
            handle_client(conn)
        except Exception as e:
            print(f"[robot_controller] Client handler error: {e}")
        finally:
            conn.close()
            print("[robot_controller] Orchestrator disconnected.")


server_thread = threading.Thread(target=server_thread_fn, daemon=True)
server_thread.start()


# ----------------------------------------------------------------------
# Main Webots simulation loop
# ----------------------------------------------------------------------
sim_time = 0.0

while robot.step(timestep) != -1:
    sim_time += timestep / 1000.0

    # Handle a timed move that needs to auto-stop
    if stop_after_move[0] and sim_time >= move_end_time[0]:
        stop_all()
        stop_after_move[0] = False

    if command_ready.is_set():
        with state_lock:
            command = pending_command
            command_ready.clear()

        cmd_type = command.get("cmd")
        response = {"ok": True, "cmd": cmd_type}

        try:
            if cmd_type == "move":
                left = float(command.get("left", 0.0))
                right = float(command.get("right", 0.0))
                duration = command.get("duration")  # seconds, optional

                set_wheel_speeds(left, right)

                if duration is not None:
                    move_end_time[0] = sim_time + float(duration)
                    stop_after_move[0] = True
                else:
                    stop_after_move[0] = False

                response["left"] = left
                response["right"] = right
                response["duration"] = duration

            elif cmd_type == "stop":
                stop_all()
                stop_after_move[0] = False

            elif cmd_type == "get_camera":
                img_b64 = capture_camera_jpeg_b64()
                if img_b64 is None:
                    response = {"ok": False, "cmd": cmd_type, "error": "no_camera"}
                else:
                    response["image_b64"] = img_b64
                    response["width"] = camera.getWidth()
                    response["height"] = camera.getHeight()

            elif cmd_type == "get_status":
                response["sim_time"] = sim_time
                response["has_camera"] = camera is not None

            else:
                response = {"ok": False, "error": f"unknown_cmd:{cmd_type}"}

        except Exception as e:
            response = {"ok": False, "error": str(e)}

        with state_lock:
            last_response = response
            response_ready.set()
