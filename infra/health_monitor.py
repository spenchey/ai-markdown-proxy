from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import boto3


DOMAINS = tuple(
    domain.strip()
    for domain in os.environ.get(
        "DOMAINS",
        "ai.motorinnautogroup.com,ai.motorinntoyotaofcarroll.com,ai.motorinnofcarroll.com",
    ).split(",")
    if domain.strip()
)
PATHS = (
    "/__health/full",
    "/llms.txt",
    "/llms?query=service&limit=1",
    "/llms/json?query=service&limit=1",
    "/new-inventory.md",
    "/robots.txt",
    "/sitemap.xml",
)
STATE_PARAMETER = os.environ.get("STATE_PARAMETER", "/motorinn/ai-markdown-proxy/health-state")
SLACK_SECRET_ID = os.environ.get("SLACK_SECRET_ID", "motorinn/ai-markdown-proxy/slack-bot-token")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0AC3BP5XPF")
METRIC_NAMESPACE = "MotorInn/AIReadableMirror"
TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "12"))


def _aws(service: str):
    return boto3.client(service)


def _request(url: str) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/markdown,application/json;q=0.9", "User-Agent": "MotorInn-AI-Mirror-Monitor/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(2_000_000)
            status = response.status
            content_type = response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        body = exc.read(64_000)
        status = exc.code
        content_type = exc.headers.get_content_type() if exc.headers else ""
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    return {
        "url": url,
        "status": status,
        "content_type": content_type,
        "body": body,
        "latency_ms": elapsed_ms,
    }


def evaluate_result(path: str, result: dict[str, Any]) -> tuple[bool, str | None, float | None]:
    if result["status"] != 200:
        return False, f"{path} returned HTTP {result['status']}", None

    content_type = result["content_type"]
    body = result["body"]
    endpoint_path = urlsplit(path).path
    if endpoint_path in ("/llms", "/llms.txt", "/llms-full.txt") or endpoint_path.endswith(".md"):
        if content_type != "text/markdown":
            return False, f"{path} returned {content_type or 'no content type'}", None
        if not body.strip():
            return False, f"{path} returned an empty document", None
    elif endpoint_path == "/llms/json":
        if content_type != "application/json":
            return False, f"{path} returned {content_type or 'no content type'}", None
        try:
            payload = json.loads(body)
            if payload.get("schema") != "motorinn.llmsQuery.v1" or int(payload.get("resultCount", 0)) <= 0:
                return False, f"{path} returned no valid query results", None
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"{path} returned invalid query JSON: {exc}", None
    elif endpoint_path == "/robots.txt" and content_type != "text/plain":
        return False, f"{path} returned {content_type or 'no content type'}", None
    elif endpoint_path == "/sitemap.xml":
        if content_type != "application/xml":
            return False, f"{path} returned {content_type or 'no content type'}", None
        if not body.strip():
            return False, f"{path} returned an empty document", None

    freshness_hours = None
    if endpoint_path == "/__health/full":
        try:
            health = json.loads(body)
            if health.get("status") != "ok" or int(health.get("matchedInventory", 0)) <= 0:
                return False, f"{path} reported no healthy matched inventory", None
            if health.get("agentQuery", {}).get("status") != "ok":
                return False, f"{path} reported an unhealthy agent query layer", None
            timestamps = [
                datetime.fromisoformat(str(health[key]).replace("Z", "+00:00"))
                for key in ("dealerVaultUpdatedAt", "catalogUpdatedAt")
                if health.get(key)
            ]
            if not timestamps:
                return False, f"{path} omitted source freshness timestamps", None
            oldest = min(timestamps)
            freshness_hours = (datetime.now(timezone.utc) - oldest).total_seconds() / 3600
            if freshness_hours > 36:
                return False, f"{path} source is {freshness_hours:.1f} hours old", freshness_hours
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"{path} returned invalid health JSON: {exc}", None
    return True, None, freshness_hours


def transition_state(previous: dict[str, Any], host_ok: dict[str, bool]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    next_state = {"hosts": {}, "updatedAt": datetime.now(timezone.utc).isoformat()}
    notifications: list[tuple[str, str]] = []
    prior_hosts = previous.get("hosts", {})
    for host, ok in host_ok.items():
        prior_failures = int(prior_hosts.get(host, {}).get("consecutiveFailures", 0))
        failures = 0 if ok else prior_failures + 1
        next_state["hosts"][host] = {"consecutiveFailures": failures, "healthy": ok}
        if failures == 2:
            notifications.append((host, "failed"))
        elif ok and prior_failures >= 2:
            notifications.append((host, "recovered"))
    return next_state, notifications


def _load_state() -> dict[str, Any]:
    ssm = _aws("ssm")
    try:
        response = ssm.get_parameter(Name=STATE_PARAMETER)
        return json.loads(response["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return {"hosts": {}}


def _save_state(state: dict[str, Any]) -> None:
    _aws("ssm").put_parameter(Name=STATE_PARAMETER, Type="String", Value=json.dumps(state), Overwrite=True)


def _slack_token() -> str:
    value = _aws("secretsmanager").get_secret_value(SecretId=SLACK_SECRET_ID)["SecretString"]
    try:
        parsed = json.loads(value)
        return parsed.get("token") or parsed.get("SLACK_BOT_TOKEN") or parsed.get("SLACK_TOKEN")
    except json.JSONDecodeError:
        return value


def _post_slack(message: str) -> None:
    payload = json.dumps({"channel": SLACK_CHANNEL_ID, "text": message}).encode()
    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {_slack_token()}", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"Slack alert failed: {result.get('error', 'unknown error')}")


def _publish_metrics(host: str, path: str, result: dict[str, Any], ok: bool, freshness_hours: float | None) -> None:
    dimensions = [{"Name": "Host", "Value": host}, {"Name": "Path", "Value": path}]
    metrics = [
        {"MetricName": "Healthy", "Dimensions": dimensions, "Value": 1 if ok else 0, "Unit": "Count"},
        {"MetricName": "Latency", "Dimensions": dimensions, "Value": result["latency_ms"], "Unit": "Milliseconds"},
        {"MetricName": "HTTPStatus", "Dimensions": dimensions, "Value": result["status"], "Unit": "None"},
    ]
    if freshness_hours is not None:
        metrics.append({"MetricName": "SourceFreshness", "Dimensions": dimensions, "Value": freshness_hours, "Unit": "None"})
    _aws("cloudwatch").put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=metrics)


def lambda_handler(_event, _context):
    host_ok: dict[str, bool] = {}
    errors: dict[str, list[str]] = {}
    for host in DOMAINS:
        host_ok[host] = True
        errors[host] = []
        for path in PATHS:
            try:
                result = _request(f"https://{host}{path}")
                ok, error, freshness_hours = evaluate_result(path, result)
            except Exception as exc:
                result = {"status": 0, "latency_ms": TIMEOUT_SECONDS * 1000}
                ok, error, freshness_hours = False, f"{path} request failed: {exc}", None
            host_ok[host] = host_ok[host] and ok
            if error:
                errors[host].append(error)
            _publish_metrics(host, path, result, ok, freshness_hours)

    previous = _load_state()
    state, notifications = transition_state(previous, host_ok)
    for host in state["hosts"]:
        state["hosts"][host]["errors"] = errors[host]
    _save_state(state)

    for host, event in notifications:
        if event == "failed":
            detail = "; ".join(errors[host]) or "unknown health failure"
            _post_slack(f":rotating_light: AI-readable mirror failed twice for `{host}`. {detail}. Owner: IT/Archie; Rory reporting is degraded until recovery.")
        else:
            _post_slack(f":white_check_mark: AI-readable mirror recovered for `{host}` after repeated failures.")

    print(json.dumps({"event": "ai_proxy_monitor", "hostStatus": host_ok, "errors": errors, "notifications": notifications}))
    return {"statusCode": 200, "body": json.dumps({"hosts": host_ok, "notifications": notifications})}
