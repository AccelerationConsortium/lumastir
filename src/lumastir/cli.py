"""Hardware-independent CLI; explicit claims for sustained setpoints."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4


def send_request(
    endpoint,
    data=None,
    method="GET",
    host="http://localhost:8000",
    *,
    token=None,
    timeout=5,
):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Claim-Token"] = token
    body = None if data is None else json.dumps(data, allow_nan=False).encode("utf-8")
    req = urllib.request.Request(
        host.rstrip("/") + endpoint, data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Cannot reach Lumastir at {host}: {exc}. A timed command may already have executed; inspect its request ID before retrying."
        ) from exc


def main():
    parser = argparse.ArgumentParser(description="Lumastir control CLI")
    parser.add_argument(
        "--host", default=os.getenv("LUMASTIR_URL", "http://localhost:8000")
    )
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--claim-token", default=os.getenv("LUMASTIR_CLAIM_TOKEN"))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "devices", "stop", "heartbeat", "release"):
        sub.add_parser(name)
    claim = sub.add_parser("claim")
    claim.add_argument("--owner", required=True)
    claim.add_argument("--session-id", default=None)
    claim.add_argument("--ttl", type=float, default=30)
    for name, field in (("motor", "speed"), ("led", "brightness")):
        command = sub.add_parser(name)
        command.add_argument("index", type=int)
        command.add_argument(field, type=float)
    run = sub.add_parser(
        "run", help="Acquire a claim, run a timed motor operation, wait, and release"
    )
    run.add_argument("index", type=int)
    run.add_argument("speed", type=float)
    run.add_argument("duration_s", type=float)
    run.add_argument("--owner", required=True)
    inspect = sub.add_parser("run-status")
    inspect.add_argument("request_id")
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be between 0 and 60 seconds")

    def call(path, data=None, method="GET", token=None):
        return send_request(
            path,
            data,
            method,
            args.host,
            token=token or args.claim_token,
            timeout=args.timeout,
        )

    try:
        if args.command == "run":
            devices = call("/v1/devices")
            request_id = str(uuid4())
            session_id = str(uuid4())
            # Print before the start request: retain this identifier even if its response is lost.
            print(
                json.dumps(
                    {"request_id": request_id, "instance_id": devices["instance_id"]}
                ),
                flush=True,
            )
            acquired = call(
                "/control/claim",
                {"owner": args.owner, "session_id": session_id},
                "POST",
            )
            token = acquired["claim_token"]
            try:
                result = call(
                    "/control/motor/run",
                    {
                        "index": args.index,
                        "speed": args.speed,
                        "duration_s": args.duration_s,
                        "request_id": request_id,
                        "instance_id": devices["instance_id"],
                    },
                    "POST",
                    token,
                )
                next_beat = time.monotonic() + acquired["heartbeat_interval_s"] / 2
                while result["state"] == "running":
                    time.sleep(0.2)
                    if time.monotonic() >= next_beat:
                        call("/control/heartbeat", {}, "POST", token)
                        next_beat = (
                            time.monotonic() + acquired["heartbeat_interval_s"] / 2
                        )
                    result = call(f"/v1/runs/{request_id}")
                if result["state"] != "completed":
                    raise RuntimeError(f"Run did not complete: {json.dumps(result)}")
            finally:
                # Release stops every output; the device's lease is the fallback on network failure.
                call("/control/release", {}, "POST", token)
        elif args.command in ("status", "devices", "run-status"):
            path = {"status": "/status", "devices": "/v1/devices"}.get(args.command)
            result = call(path or f"/v1/runs/{args.request_id}")
        elif args.command == "claim":
            result = call(
                "/control/claim",
                {
                    "owner": args.owner,
                    "session_id": args.session_id or str(uuid4()),
                    "ttl_s": args.ttl,
                },
                "POST",
            )
        elif args.command in ("stop", "heartbeat", "release"):
            result = call(f"/control/{args.command}", {}, "POST")
        else:
            field = "speed" if args.command == "motor" else "brightness"
            result = call(
                f"/control/{args.command}/set",
                {"index": args.index, field: getattr(args, field)},
                "POST",
            )
        print(json.dumps(result, indent=2))
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print(
            "Interrupted. Release was attempted; verify outputs if the connection failed.",
            file=sys.stderr,
        )
        raise SystemExit(130)


if __name__ == "__main__":
    main()
