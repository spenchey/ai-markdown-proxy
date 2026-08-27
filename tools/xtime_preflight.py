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
from server import SITES  # noqa: E402


REQUIREMENTS = ("none", "configured", "verified", "active")


def _safe_site_status(site: object) -> tuple[dict[str, object], bool]:
    stable_handoff_url = f"https://{site.ai_host}/service-scheduler"
    evaluation = agent_access.xtime_configuration_preflight(site, os.environ)
    status = {
        "site": site.key,
        "provider": evaluation["targetProvider"],
        "configured": evaluation["configured"],
        "rooftopBindingVerified": evaluation["rooftopBindingVerified"],
        "active": evaluation["active"],
        "status": evaluation["status"],
        "stableHandoffUrl": stable_handoff_url,
    }
    if "error" in evaluation:
        status["error"] = evaluation["error"]
    return status, bool(evaluation["configurationValid"])


def _requirement_satisfied(requirement: str, sites: list[dict[str, object]]) -> bool:
    if requirement == "none":
        return True
    if requirement == "configured":
        return all(site["configured"] is True for site in sites)
    if requirement == "verified":
        return all(
            site["configured"] is True and site["rooftopBindingVerified"] is True
            for site in sites
        )
    return all(site["active"] is True for site in sites)


def preflight(requirement: str) -> tuple[dict[str, object], int]:
    statuses: list[dict[str, object]] = []
    configuration_valid = True
    for site in SITES.values():
        status, valid = _safe_site_status(site)
        statuses.append(status)
        configuration_valid = configuration_valid and valid

    requirement_satisfied = (
        configuration_valid and _requirement_satisfied(requirement, statuses)
    )
    payload = {
        "schema": "motorinn.xtimePreflight.v1",
        "requirement": requirement,
        "configurationValid": configuration_valid,
        "requirementSatisfied": requirement_satisfied,
        "sites": statuses,
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
