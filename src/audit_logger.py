"""
Logging & Audit Module for Dispute Defense Copilot.

Provides:
- Structured JSON application logging (console + rotating file)
- Append-only JSONL audit trail for pipeline actions
- Typed helper functions for every pipeline event
- Query utility for reading/filtering the audit trail

Event Types:
    DISPUTE_ANALYZED   – Full pipeline run completed for a dispute
    EVIDENCE_VERIFIED  – Single evidence document verified
    DECISION_MADE      – Policy engine produced a recommendation
    WHATIF_RUN         – What-if simulation completed
    MODEL_LOADED       – ML model loaded from disk
    TRAINING_COMPLETE  – Training finished with metrics
    API_REQUEST        – Inbound HTTP request served
"""

import json
import logging
import logging.handlers
import os
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
_APP_LOG_PATH = os.path.join(_LOG_DIR, "app.log")
_AUDIT_TRAIL_PATH = os.path.join(_LOG_DIR, "audit_trail.jsonl")

# Ensure the log directory exists on import
os.makedirs(_LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

class EventType:
    DISPUTE_ANALYZED = "DISPUTE_ANALYZED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    DECISION_MADE = "DECISION_MADE"
    WHATIF_RUN = "WHATIF_RUN"
    MODEL_LOADED = "MODEL_LOADED"
    TRAINING_COMPLETE = "TRAINING_COMPLETE"
    API_REQUEST = "API_REQUEST"


# ---------------------------------------------------------------------------
# JSON Formatter
# ---------------------------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """Serialize every log record as a single-line JSON object."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


# ---------------------------------------------------------------------------
# Pretty Console Formatter
# ---------------------------------------------------------------------------

class _PrettyFormatter(logging.Formatter):
    """Human-readable coloured output for terminal use."""

    COLORS = {
        "DEBUG": "\033[90m",     # grey
        "INFO": "\033[36m",      # cyan
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[91m",  # bright red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        return f"{color}[{ts}] {record.levelname:<8}{self.RESET} {record.getMessage()}"


# ---------------------------------------------------------------------------
# Logger Factory (singleton-ish per name)
# ---------------------------------------------------------------------------

_loggers_configured: set = set()


def get_logger(name: str = "dispute_copilot") -> logging.Logger:
    """
    Return a configured logger.

    First call per *name* attaches:
    - A pretty-printing StreamHandler (console)
    - A RotatingFileHandler writing JSON lines to logs/app.log
    """
    logger = logging.getLogger(name)

    if name in _loggers_configured:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler — pretty
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(_PrettyFormatter())
    logger.addHandler(console)

    # File handler — JSON, rotating
    file_handler = logging.handlers.RotatingFileHandler(
        _APP_LOG_PATH,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_JSONFormatter())
    logger.addHandler(file_handler)

    _loggers_configured.add(name)
    return logger


# ---------------------------------------------------------------------------
# Audit Trail — append-only JSONL writer
# ---------------------------------------------------------------------------

def _write_audit_entry(entry: dict) -> None:
    """Append a single JSON object as one line to the audit trail file."""
    with open(_AUDIT_TRAIL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def log_event(event_type: str, payload: dict, dispute_id: str | None = None) -> dict:
    """
    Record an audit event.

    Parameters
    ----------
    event_type : str
        One of the EventType constants.
    payload : dict
        Arbitrary event-specific data.
    dispute_id : str, optional
        Associated dispute ID (if applicable).

    Returns
    -------
    dict
        The full audit entry that was persisted (including generated fields).
    """
    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dispute_id": dispute_id,
        "payload": payload,
    }
    _write_audit_entry(entry)

    logger = get_logger()
    logger.info("[AUDIT] %s | dispute=%s", event_type, dispute_id or "N/A")
    return entry


# ---------------------------------------------------------------------------
# Typed helper functions
# ---------------------------------------------------------------------------

def log_dispute_analysis(dispute_id: str, response: dict) -> dict:
    """Log a completed dispute analysis run."""
    return log_event(
        EventType.DISPUTE_ANALYZED,
        {
            "win_probability": response.get("win_probability"),
            "decision_action": response.get("decision", {}).get("action"),
            "evidence_count": len(response.get("verifier_results", [])),
            "reason_code": response.get("reason_code"),
        },
        dispute_id=dispute_id,
    )


def log_evidence_verification(dispute_id: str, result: dict) -> dict:
    """Log a single evidence document verification."""
    return log_event(
        EventType.EVIDENCE_VERIFIED,
        {
            "evidence_type": result.get("evidence_type"),
            "predicted_valid": result.get("predicted_valid"),
            "confidence": result.get("confidence"),
            "is_relevant": result.get("is_relevant"),
            "field_match_count": result.get("field_match_count"),
            "mismatch_count": len(result.get("field_mismatches", [])),
        },
        dispute_id=dispute_id,
    )


def log_decision(dispute_id: str, action: str, reason: str, context: dict | None = None) -> dict:
    """Log a policy decision."""
    return log_event(
        EventType.DECISION_MADE,
        {
            "action": action,
            "reason": reason,
            **(context or {}),
        },
        dispute_id=dispute_id,
    )


def log_whatif(dispute_id: str, results: list) -> dict:
    """Log what-if simulation results."""
    return log_event(
        EventType.WHATIF_RUN,
        {
            "scenario_count": len(results),
            "top_scenario": results[0] if results else None,
        },
        dispute_id=dispute_id,
    )


def log_model_loaded(model_name: str, path: str) -> dict:
    """Log that a model was loaded from disk."""
    return log_event(
        EventType.MODEL_LOADED,
        {"model_name": model_name, "path": path},
    )


def log_training_complete(metrics: dict) -> dict:
    """Log that a training run has completed."""
    return log_event(
        EventType.TRAINING_COMPLETE,
        {"metrics": metrics},
    )


def log_api_request(method: str, path: str, status_code: int, dispute_id: str | None = None) -> dict:
    """Log an inbound API request."""
    return log_event(
        EventType.API_REQUEST,
        {"method": method, "path": path, "status_code": status_code},
        dispute_id=dispute_id,
    )


# ---------------------------------------------------------------------------
# Audit Trail Reader / Query
# ---------------------------------------------------------------------------

def read_audit_trail(
    dispute_id: str | None = None,
    event_type: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Read the audit trail and optionally filter entries.

    Parameters
    ----------
    dispute_id : str, optional
        Return only entries for this dispute.
    event_type : str, optional
        Return only entries of this type.
    limit : int
        Maximum number of entries to return (most recent first).

    Returns
    -------
    list[dict]
        Matching audit entries, newest first.
    """
    if not os.path.exists(_AUDIT_TRAIL_PATH):
        return []

    entries: list[dict] = []
    with open(_AUDIT_TRAIL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if dispute_id and entry.get("dispute_id") != dispute_id:
                continue
            if event_type and entry.get("event_type") != event_type:
                continue

            entries.append(entry)

    # Most recent first, capped at limit
    entries.reverse()
    return entries[:limit]
