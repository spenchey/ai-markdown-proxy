#!/usr/bin/env python3
"""Validate staged Xtime configuration without disclosing tenant values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import agent_access  # noqa: E402


REQUIREMENTS = ("none", "configured", "verified", "active")
STABLE_HANDOFF_URLS = [
    "https://ai.motorinnautogroup.com/service-scheduler",
    "https://ai.motorinnofcarroll.com/service-scheduler",
    "https://ai.motorinntoyotaofcarroll.com/service-scheduler",
]


def _safe_location_status() -> tuple[dict[str, object], bool]:
    evaluation = agent_access.xtime_configuration_preflight(os.environ)
    status = {
        "location": "carroll",
        "name": "Carroll",
        "provider": evaluation["targetProvider"],
        "configured": evaluation["configured"],
        "locationBindingVerified": evaluation["locationBindingVerified"],
        "active": evaluation["active"],
        "status": evaluation["status"],
        "stableHandoffUrls": STABLE_HANDOFF_URLS,
    }
    if "error" in evaluation:
        status["error"] = evaluation["error"]
    return status, bool(evaluation["configurationValid"])


def _requirement_satisfied(requirement: str, locations: list[dict[str, object]]) -> bool:
    if requirement == "none":
        return True
    if requirement == "configured":
        return all(location["configured"] is True for location in locations)
    if requirement == "verified":
        return all(
            location["configured"] is True
            and location["locationBindingVerified"] is True
            for location in locations
        )
    return all(location["active"] is True for location in locations)


def preflight(requirement: str) -> tuple[dict[str, object], int]:
    status, configuration_valid = _safe_location_status()
    locations = [status]

    requirement_satisfied = (
        configuration_valid and _requirement_satisfied(requirement, locations)
    )
    payload = {
        "schema": "motorinn.xtimePreflight.v1",
        "requirement": requirement,
        "configurationValid": configuration_valid,
        "requirementSatisfied": requirement_satisfied,
        "locations": locations,
    }
    return payload, 0 if requirement_satisfied else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate safe Xtime activation gates without printing provider URLs."
    )
    parser.add_argument("--require", choices=REQUIREMENTS, default="none")
    args = parser.parse_args()
    payload, exit_code = preflight(args.require)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
