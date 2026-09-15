"""
webots_client.py
-----------------
Thin TCP client for talking to robot_controller.py, which runs inside Webots.

Protocol: newline-delimited JSON, one request -> one response per line.
"""

import json
import socket

HOST = "127.0.0.1"
PORT = 10101


class WebotsClient:
    def __init__(self, host=HOST, port=PORT, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.sock_file = None
        self._connect()

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        self.sock_file = self.sock.makefile("rwb")

    def _send(self, command: dict) -> dict:
        line = (json.dumps(command) + "\n").encode("utf-8")
        try:
            self.sock_file.write(line)
            self.sock_file.flush()
            response_line = self.sock_file.readline()
            if not response_line:
                raise ConnectionError("Webots controller closed the connection.")
            return json.loads(response_line.decode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Try reconnecting once
            self._connect()
            self.sock_file.write(line)
            self.sock_file.flush()
            response_line = self.sock_file.readline()
            return json.loads(response_line.decode("utf-8"))

    def move(self, left: float, right: float, duration: float = None) -> dict:
        cmd = {"cmd": "move", "left": left, "right": right}
        if duration is not None:
            cmd["duration"] = duration
        return self._send(cmd)

    def stop(self) -> dict:
        return self._send({"cmd": "stop"})

    def get_camera(self) -> dict:
        return self._send({"cmd": "get_camera"})

    def get_status(self) -> dict:
        return self._send({"cmd": "get_status"})

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
