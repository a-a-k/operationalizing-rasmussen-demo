"""Instrumented client and forwarding workers for hosted-only runtime execution."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOCK = threading.RLock()
STATE = {"config": None, "counts": Counter()}
LOG = None
ARGS = None


def journal(event):
    # An event journal, not a serialization of the observer's aggregate counters.
    with LOCK:
        LOG.write(json.dumps(event, separators=(",", ":")) + "\n")
        LOG.flush()


def fetch(url, headers=None, timeout=1):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}),
                                    timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        return 599, type(exc).__name__.encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, code=200):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if ARGS.role != "gateway" or self.path != "/configuration":
            return self.reply({}, 404)
        config = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with LOCK:
            stamp = time.time_ns() / 1e6
            STATE["config"] = config
            journal({"type": "configuration_applied", "applied_ms": stamp, "config": config})
        self.reply({"applied_ms": stamp, "configuration_version": config["version"]})

    def do_GET(self):
        if self.path == "/health":
            return self.reply({"ok": True})
        if ARGS.role == "worker":
            return self.worker()
        if self.path == "/snapshot":
            with LOCK:
                config = copy.deepcopy(STATE["config"])
                if config is None:
                    return self.reply({"ready": False})
                stamp = time.time_ns() / 1e6
                closed = min(config["windows"], math.floor(
                    (stamp - config["origin_ms"]) / (1000 * config["window_seconds"])))
                rows = [{"deployment": d, "component": c, "kind": k, "count": n}
                        for (w, d, c, k), n in STATE["counts"].items() if w == closed]
                result = {"ready": closed > 0, "window": closed, "counts": rows,
                          "policy_version": config["policy_version"],
                          "configuration_version": config["version"],
                          "generated_ms": stamp,
                          "window_end_ms": config["origin_ms"] + closed * config["window_seconds"] * 1000}
            return self.reply(result)
        group = self.path.removeprefix("/request/").split("?")[0]
        if group not in ("catalog", "currency"):
            return self.reply({}, 404)
        logical_id = self.headers.get("X-Logical-Id", "")
        with LOCK:
            config = copy.deepcopy(STATE["config"])
        if not config or not logical_id:
            return self.reply({}, 503)
        begin = time.time_ns() / 1e6
        journal({"type": "logical_start", "logical_id": logical_id, "logical_group": group,
                 "started_ms": begin, "configuration": config["version"]})
        last_code, payload = 599, b"{}"
        for index in range(config["max_attempts"]):
            # Route pinning for one logical call avoids mixing retry semantics mid-call.
            candidates = config["routes"][group]
            selector = int(hashlib.sha256(f"{logical_id}:{index}".encode()).hexdigest(), 16)
            target = candidates[selector % len(candidates)]
            kind = "first" if index == 0 else "retry"
            with LOCK:
                stamp = time.time_ns() / 1e6
                window = math.floor((stamp - config["origin_ms"]) / (1000 * config["window_seconds"])) + 1
                STATE["counts"][window, config["deployment"], target, kind] += 1
                journal({"type": "attempt_start", "logical_id": logical_id, "attempt": index,
                         "logical_group": group, "started_ms": stamp, "component": target,
                         "deployment": config["deployment"], "configuration": config["version"]})
            last_code, payload = fetch(f"http://{target}:8080/read/{group}", {
                "X-Logical-Id": logical_id, "X-Attempt": str(index),
                "X-Fault-Probability": str(config["fault_probability"]),
                "X-Fault-Seed": str(config["seed"]),
            }, timeout=config["attempt_timeout_seconds"] + 0.2)
            journal({"type": "attempt_end", "logical_id": logical_id, "attempt": index,
                     "ended_ms": time.time_ns() / 1e6, "status": last_code})
            if 200 <= last_code < 300:
                break
        journal({"type": "logical_end", "logical_id": logical_id, "logical_group": group,
                 "ended_ms": time.time_ns() / 1e6, "status": last_code,
                 "latency_ms": time.time_ns() / 1e6 - begin, "attempts": index + 1})
        self.reply(payload, code=200 if 200 <= last_code < 300 else 503)

    def worker(self):
        group = self.path.removeprefix("/read/").split("?")[0]
        path = {"catalog": "/api/products", "currency": "/api/currency"}.get(group)
        if path is None:
            return self.reply({}, 404)
        logical_id = self.headers.get("X-Logical-Id")
        index = self.headers.get("X-Attempt", "0")
        start = time.time_ns() / 1e6
        status, payload = fetch("http://frontend:8080" + path, timeout=ARGS.timeout)
        draw = int(hashlib.sha256(
            f"{self.headers.get('X-Fault-Seed')}:{logical_id}:{index}".encode()).hexdigest()[:16], 16) / 2**64
        injected = 200 <= status < 300 and draw < float(self.headers.get("X-Fault-Probability", "0"))
        journal({"type": "forwarded_attempt", "logical_id": logical_id, "attempt": int(index),
                 "logical_group": group, "component": ARGS.component,
                 "upstream_started_ms": start, "upstream_ended_ms": time.time_ns() / 1e6,
                 "upstream_status": status, "injected_delivery_failure": injected})
        self.reply(b'{"delivery_failure":true}' if injected else payload,
                   code=503 if injected else (200 if status == 200 else 502))


def main():
    global ARGS, LOG
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["gateway", "worker"], required=True)
    parser.add_argument("--component", default="gateway")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1)
    ARGS = parser.parse_args()
    ARGS.output.parent.mkdir(parents=True, exist_ok=True)
    LOG = ARGS.output.open("a", encoding="utf-8", buffering=1)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
