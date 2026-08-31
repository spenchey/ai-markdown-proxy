#!/usr/bin/env python3
"""Run the bounded Motor Inn cross-agent read conformance canary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from read_conformance import (  # noqa: E402
    CLIENTS,
    DEFAULT_HOSTS,
    ReadConformanceHarness,
    RequestsTransport,
    exit_code,
    load_client_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Motor Inn public AI pages, OpenAPI reads, MCP reads, and optional client evidence."
    )
    parser.add_argument("--host", action="append", choices=DEFAULT_HOSTS, dest="hosts")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--vehicle-limit", type=int, default=10)
    parser.add_argument("--client-evidence", action="append", type=Path, default=[])
    parser.add_argument("--require-client", action="append", choices=sorted(CLIENTS), default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    evidence = load_client_evidence(args.client_evidence)
    harness = ReadConformanceHarness(
        RequestsTransport(timeout_seconds=args.timeout),
        vehicle_limit=args.vehicle_limit,
    )
    report = harness.run(
        args.hosts or list(DEFAULT_HOSTS),
        client_evidence=evidence,
        required_clients=set(args.require_client),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
