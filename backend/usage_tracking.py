"""Utilities for privacy-safe usage telemetry."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import threading
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from .database import get_data_dir
from refchecker.utils.url_utils import extract_arxiv_id_from_url


_ANALYTICS_SECRET_ENV_VAR = "REFCHECKER_ANALYTICS_SECRET"
_ANALYTICS_SECRET_FILE_NAME = ".analytics.secret"
_USAGE_LOG_PATH_ENV_VAR = "REFCHECKER_USAGE_LOG_PATH"
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?$", re.IGNORECASE)
_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER_TITLES = {
    "unknown paper",
    "processing...",
    "pasted text",
    "",
}
_USAGE_LOG_LOCK = threading.Lock()


def utcnow_sqlite() -> str:
    """Return the current UTC timestamp in SQLite-friendly format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _get_analytics_secret() -> bytes:
    configured = (
        os.environ.get(_ANALYTICS_SECRET_ENV_VAR, "").strip()
        or os.environ.get("REFCHECKER_SECRET_KEY", "").strip()
    )
    if configured:
        return configured.encode("utf-8")

    secret_path = get_data_dir() / _ANALYTICS_SECRET_FILE_NAME
    if secret_path.exists():
        return secret_path.read_bytes()

    secret = os.urandom(32)
    secret_path.write_bytes(secret)
    if os.name != "nt":
        os.chmod(secret_path, 0o600)
    return secret


def get_usage_log_path() -> Path:
    """Return the JSONL file used for structured usage telemetry."""
    configured = os.environ.get(_USAGE_LOG_PATH_ENV_VAR, "").strip()
    if configured:
        log_path = Path(configured).expanduser()
    else:
        log_path = get_data_dir() / "logs" / "usage-events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def stable_hash(value: Optional[str]) -> Optional[str]:
    """Return a deterministic keyed hash suitable for telemetry fields."""
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    digest = hmac.new(_get_analytics_secret(), normalized.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def extract_email_domain(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].strip().lower() or None


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clean_event(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, nested in value.items()
            if (cleaned := _clean_event(nested)) is not None
        }
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _clean_event(item)) is not None]
    if value is None:
        return None
    return value


def _append_usage_event_sync(event: Dict[str, Any]) -> None:
    log_path = get_usage_log_path()
    payload = _clean_event(event) or {}
    with _USAGE_LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=_json_default))
            handle.write("\n")


async def append_usage_event(event: Dict[str, Any]) -> None:
    """Append a structured usage event to the JSONL telemetry file."""
    await asyncio.to_thread(_append_usage_event_sync, event)


def _iter_usage_events() -> Iterable[Dict[str, Any]]:
    log_path = get_usage_log_path()
    if not log_path.exists():
        return []

    events = []
    with log_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


async def get_usage_events(
    limit: int = 100,
    event_type: Optional[str] = None,
    user_id: Optional[int] = None,
) -> list[Dict[str, Any]]:
    """Return recent usage events from the JSONL telemetry file."""

    def _read_events() -> list[Dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        matches: deque[Dict[str, Any]] = deque(maxlen=safe_limit)
        for event in _iter_usage_events():
            if event_type and event.get("event_type") != event_type:
                continue
            if user_id is not None and event.get("user_id") != user_id:
                continue
            matches.append(event)
        return list(reversed(matches))

    return await asyncio.to_thread(_read_events)


def _parse_event_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def get_usage_summary(days: int = 30) -> Dict[str, Any]:
    """Return an admin-facing summary built from the JSONL telemetry file."""

    def _build_summary() -> Dict[str, Any]:
        safe_days = max(1, min(days, 365))
        cutoff = datetime.now(timezone.utc) - timedelta(days=safe_days)
        unique_users = set()
        unique_papers = set()
        durations: list[int] = []
        top_users: Dict[Any, Dict[str, Any]] = {}
        top_papers: Dict[str, Dict[str, Any]] = {}
        top_source_hosts: Counter[str] = Counter()
        issue_totals: Counter[str] = Counter()
        abuse_signals: Counter[tuple[str, str]] = Counter()

        totals = {
            "total_checks": 0,
            "unique_users": 0,
            "unique_papers": 0,
            "completed_checks": 0,
            "failed_checks": 0,
            "cancelled_checks": 0,
            "total_refs": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "total_suggestions": 0,
            "total_unverified": 0,
            "total_hallucinations": 0,
            "avg_duration_ms": 0,
        }

        for event in _iter_usage_events():
            occurred_at = _parse_event_time(event.get("occurred_at"))
            if occurred_at and occurred_at < cutoff:
                continue

            event_type = event.get("event_type")
            user_id = event.get("user_id")
            paper_group = event.get("paper_key") or event.get("paper_title") or "unknown"
            source_host = event.get("source_host")
            payload = event.get("payload") or {}

            if user_id is not None:
                unique_users.add(user_id)
            if event.get("paper_key"):
                unique_papers.add(event["paper_key"])

            if user_id not in top_users:
                top_users[user_id] = {
                    "user_id": user_id,
                    "user_label": event.get("email_domain") or event.get("provider") or (f"User {user_id}" if user_id is not None else "Anonymous"),
                    "check_count": 0,
                    "total_refs": 0,
                    "completed_checks": 0,
                    "failed_checks": 0,
                    "cancelled_checks": 0,
                }

            if paper_group not in top_papers:
                top_papers[paper_group] = {
                    "paper_group": paper_group,
                    "paper_title": event.get("paper_title"),
                    "source_host": source_host,
                    "check_count": 0,
                    "total_refs": 0,
                    "total_errors": 0,
                    "total_warnings": 0,
                    "total_hallucinations": 0,
                }

            if event_type == "check.started":
                totals["total_checks"] += 1
                top_users[user_id]["check_count"] += 1
                top_papers[paper_group]["check_count"] += 1
                if source_host:
                    top_source_hosts[source_host] += 1
            elif event_type == "check.completed":
                totals["completed_checks"] += 1
                top_users[user_id]["completed_checks"] += 1
                total_refs = int(payload.get("total_refs") or 0)
                errors_count = int(payload.get("errors_count") or 0)
                warnings_count = int(payload.get("warnings_count") or 0)
                suggestions_count = int(payload.get("suggestions_count") or 0)
                unverified_count = int(payload.get("unverified_count") or 0)
                hallucination_count = int(payload.get("hallucination_count") or 0)
                totals["total_refs"] += total_refs
                totals["total_errors"] += errors_count
                totals["total_warnings"] += warnings_count
                totals["total_suggestions"] += suggestions_count
                totals["total_unverified"] += unverified_count
                totals["total_hallucinations"] += hallucination_count
                top_users[user_id]["total_refs"] += total_refs
                top_papers[paper_group]["total_refs"] += total_refs
                top_papers[paper_group]["total_errors"] += errors_count
                top_papers[paper_group]["total_warnings"] += warnings_count
                top_papers[paper_group]["total_hallucinations"] += hallucination_count
                if payload.get("duration_ms") is not None:
                    durations.append(int(payload["duration_ms"]))
                for issue_type, count in (payload.get("issue_type_counts") or {}).items():
                    issue_totals[issue_type] += int(count)
            elif event_type == "check.failed":
                totals["failed_checks"] += 1
                top_users[user_id]["failed_checks"] += 1
                if payload.get("duration_ms") is not None:
                    durations.append(int(payload["duration_ms"]))
            elif event_type == "check.cancelled":
                totals["cancelled_checks"] += 1
                top_users[user_id]["cancelled_checks"] += 1
                if payload.get("duration_ms") is not None:
                    durations.append(int(payload["duration_ms"]))

            if event_type in {"check.rate_limited", "batch.rate_limited", "auth.login_failed", "auth.websocket_denied"}:
                abuse_signals[(event_type, event.get("reason_code") or "unknown")] += 1

            if not top_papers[paper_group].get("paper_title") and event.get("paper_title"):
                top_papers[paper_group]["paper_title"] = event.get("paper_title")
            if not top_papers[paper_group].get("source_host") and source_host:
                top_papers[paper_group]["source_host"] = source_host

        totals["unique_users"] = len(unique_users)
        totals["unique_papers"] = len(unique_papers)
        if durations:
            totals["avg_duration_ms"] = int(sum(durations) / len(durations))

        return {
            "window_days": safe_days,
            "log_path": str(get_usage_log_path()),
            "totals": totals,
            "top_users": sorted(top_users.values(), key=lambda item: (-item["check_count"], -item["total_refs"], str(item["user_label"])))[:10],
            "top_papers": sorted(top_papers.values(), key=lambda item: (-item["check_count"], -item["total_refs"], str(item["paper_group"])))[:10],
            "top_source_hosts": [
                {"source_host": source_host, "check_count": count}
                for source_host, count in top_source_hosts.most_common(10)
            ],
            "top_issue_types": [
                {"issue_type": issue_type, "count": count}
                for issue_type, count in issue_totals.most_common(10)
            ],
            "abuse_signals": [
                {"event_type": event_type, "reason_code": reason_code, "count": count}
                for (event_type, reason_code), count in abuse_signals.most_common(10)
            ],
        }

    return await asyncio.to_thread(_build_summary)


async def clear_usage_log() -> int:
    """Delete the JSONL telemetry file and return the number of events removed."""

    def _clear_log() -> int:
        log_path = get_usage_log_path()
        if not log_path.exists():
            return 0
        with _USAGE_LOG_LOCK:
            with log_path.open("r", encoding="utf-8") as handle:
                line_count = sum(1 for _ in handle if _.strip())
            log_path.unlink(missing_ok=True)
        return line_count

    return await asyncio.to_thread(_clear_log)


def get_request_metadata(connection: Any) -> Dict[str, Optional[str]]:
    """Extract privacy-safe request metadata from a Request or WebSocket."""
    if connection is None:
        return {
            "request_id": None,
            "client_ip_hash": None,
            "user_agent_hash": None,
        }

    headers = getattr(connection, "headers", {}) or {}
    header_get = headers.get if hasattr(headers, "get") else lambda _key, default=None: default

    forwarded_for = header_get("x-forwarded-for")
    real_ip = header_get("x-real-ip")
    client = getattr(connection, "client", None)
    client_host = getattr(client, "host", None)
    if forwarded_for:
        client_host = forwarded_for.split(",", 1)[0].strip()
    elif real_ip:
        client_host = real_ip.strip()

    request_id = header_get("x-request-id") or header_get("x-correlation-id")
    user_agent = header_get("user-agent")
    return {
        "request_id": request_id or None,
        "client_ip_hash": stable_hash(client_host),
        "user_agent_hash": stable_hash(user_agent),
    }


def infer_source_host(source_type: Optional[str], source_value: Optional[str]) -> Optional[str]:
    if not source_value or source_type != "url":
        return None

    parsed = urlparse(source_value)
    if parsed.hostname:
        return parsed.hostname.rstrip(".").lower()

    if extract_arxiv_id(source_value):
        return "arxiv.org"
    if extract_doi(source_value):
        return "doi.org"
    return None


def extract_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    extracted = extract_arxiv_id_from_url(value)
    if extracted:
        return extracted.lower()
    stripped = value.strip()
    if _ARXIV_ID_RE.match(stripped):
        return re.sub(r"v\d+$", "", stripped, flags=re.IGNORECASE).lower()
    return None


def extract_doi(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    match = _DOI_RE.search(value)
    if not match:
        return None
    return match.group(1).rstrip(").,; ").lower()


def normalize_title_for_key(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    normalized = _TITLE_TOKEN_RE.sub("-", title.strip().lower()).strip("-")
    if not normalized or normalized in _PLACEHOLDER_TITLES:
        return None
    return normalized[:200]


def infer_paper_identity(
    paper_source: Optional[str],
    paper_title: Optional[str] = None,
    source_type: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Infer a stable paper identifier without logging raw local paths."""
    arxiv_id = extract_arxiv_id(paper_source) or extract_arxiv_id(paper_title)
    if arxiv_id:
        return {
            "paper_identifier_type": "arxiv",
            "paper_identifier_value": arxiv_id,
            "paper_key": f"arxiv:{arxiv_id}",
            "source_host": infer_source_host(source_type, paper_source) or "arxiv.org",
        }

    doi = extract_doi(paper_source) or extract_doi(paper_title)
    if doi:
        return {
            "paper_identifier_type": "doi",
            "paper_identifier_value": doi,
            "paper_key": f"doi:{doi}",
            "source_host": infer_source_host(source_type, paper_source),
        }

    normalized_title = normalize_title_for_key(paper_title)
    if normalized_title:
        return {
            "paper_identifier_type": "title",
            "paper_identifier_value": normalized_title,
            "paper_key": f"title:{normalized_title}",
            "source_host": infer_source_host(source_type, paper_source),
        }

    if source_type == "url" and paper_source:
        parsed = urlparse(paper_source)
        if parsed.hostname:
            path = (parsed.path or "").rstrip("/").lower()
            normalized_url = f"{parsed.hostname.rstrip('.').lower()}{path}"
            return {
                "paper_identifier_type": "url",
                "paper_identifier_value": normalized_url,
                "paper_key": f"url:{normalized_url}",
                "source_host": parsed.hostname.rstrip(".").lower(),
            }

    return {
        "paper_identifier_type": None,
        "paper_identifier_value": None,
        "paper_key": None,
        "source_host": infer_source_host(source_type, paper_source),
    }


def infer_bibliography_source_kind(extraction_method: Optional[str]) -> Optional[str]:
    if not extraction_method:
        return None
    extraction_method = extraction_method.lower()
    if extraction_method in {"bbl", "bib", "cache", "llm", "text"}:
        return extraction_method
    if extraction_method in {"pdf", "file"}:
        return "pdf"
    return extraction_method


def build_issue_type_counts(results: Optional[list[dict[str, Any]]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results or []:
        status = str(result.get("status") or "").strip().lower()
        if status:
            key = f"status:{status}"
            counts[key] = counts.get(key, 0) + 1

        for field, prefix in (("errors", "error"), ("warnings", "warning")):
            for item in result.get(field) or []:
                issue_type = str(item.get("error_type") or "unknown").strip().lower()
                key = f"{prefix}:{issue_type}"
                counts[key] = counts.get(key, 0) + 1

    return counts