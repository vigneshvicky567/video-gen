"""
Pure Python helper module for property-based tests of the project-init feature.

These functions mirror the logic implemented in the Bash scripts
(check-prereqs.sh, validate.sh) so that Hypothesis property tests can
validate the core algorithms without shelling out.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EnvGuardResult:
    env_file_exists: bool
    key_present: bool
    key_is_placeholder: bool
    key_is_empty: bool
    passed: bool
    output: str  # human-readable message


@dataclass
class HealthCheckResult:
    service_name: str
    port: int
    http_status: int
    body: str
    passed: bool
    output: str  # human-readable message


@dataclass
class SmokeTestResult:
    job_id: Optional[str]
    post_status: int
    post_body: str
    job_status: Optional[str]
    passed: bool
    failure_reason: Optional[str]


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

# Regex that finds the first occurrence of a version number like
# "24.0.5", "2.39.2", "v2.20.0", tolerating pre-release suffixes.
_SEMVER_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")


def parse_semver(version_string: str) -> tuple[int, int, int]:
    """Extract (major, minor, patch) from a raw version string.

    Handles strings produced by:
      - ``docker --version``        e.g. "Docker version 24.0.5, build ..."
      - ``docker compose version``  e.g. "Docker Compose version v2.20.0"
      - ``git --version``           e.g. "git version 2.39.2"

    Tolerates pre-release suffixes and missing patch components (defaults
    patch to 0).

    Raises ValueError if no version number can be found.
    """
    match = _SEMVER_RE.search(version_string)
    if not match:
        raise ValueError(f"No version number found in: {version_string!r}")

    parts = match.group(0).split(".")
    major = int(parts[0])
    minor = int(parts[1])
    patch = int(parts[2]) if len(parts) >= 3 else 0
    return (major, minor, patch)


def version_gte(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Return True if (major, minor) tuple *a* is >= *b*."""
    return a >= b


# ---------------------------------------------------------------------------
# Env guard helper
# ---------------------------------------------------------------------------

def check_env_key(env_content: str, key: str, placeholder: str) -> EnvGuardResult:
    """Parse *env_content* (the text of a .env file, not a path) and return
    an :class:`EnvGuardResult` describing the state of *key*.

    Rules:
    - ``key_present``        – the key appears in the content
    - ``key_is_empty``       – the value is the empty string or whitespace-only
    - ``key_is_placeholder`` – the value equals *placeholder* exactly
    - ``passed``             – True only when key is present AND not empty AND
                               not placeholder
    """
    key_present = False
    key_is_empty = False
    key_is_placeholder = False
    value: Optional[str] = None

    for line in env_content.splitlines():
        # Strip inline comments and leading/trailing whitespace
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        if k.strip() == key:
            key_present = True
            value = v  # keep raw value (may have trailing comment)
            # Remove inline comment (anything after an unquoted #)
            # Simple heuristic: split on " #" to avoid breaking values that
            # contain '#' as part of a hash/token.
            if " #" in value:
                value = value[: value.index(" #")]
            value = value.strip()
            break

    if key_present and value is not None:
        key_is_empty = value == "" or value.isspace()
        key_is_placeholder = value == placeholder

    passed = key_present and not key_is_empty and not key_is_placeholder

    if passed:
        output = f"{key} is set."
    else:
        reasons = []
        if not key_present:
            reasons.append(f"{key} is not present in the env file")
        elif key_is_placeholder:
            reasons.append(
                f"{key} is still set to the placeholder value '{placeholder}'"
            )
        elif key_is_empty:
            reasons.append(f"{key} is empty")
        output = "ERROR: " + "; ".join(reasons) + "."

    return EnvGuardResult(
        env_file_exists=True,  # caller is responsible for file existence check
        key_present=key_present,
        key_is_placeholder=key_is_placeholder,
        key_is_empty=key_is_empty,
        passed=passed,
        output=output,
    )


# ---------------------------------------------------------------------------
# Health check helper
# ---------------------------------------------------------------------------

_EXPECTED_HEALTH_BODY = '{"status": "ok"}'


def parse_health_response(
    http_status: int,
    body: str,
    service_name: str,
    port: int,
) -> HealthCheckResult:
    """Return a :class:`HealthCheckResult` for a single /health response.

    ``passed`` is True iff *http_status* == 200 AND *body* == '{"status": "ok"}'.
    On failure the output contains *service_name*, str(*port*), str(*http_status*),
    and *body*.
    """
    passed = http_status == 200 and body == _EXPECTED_HEALTH_BODY

    if passed:
        output = f"✓ {service_name} (:{port}) is healthy."
    else:
        output = (
            f"FAIL: {service_name} (:{port}) — "
            f"HTTP {http_status}, body: {body}"
        )

    return HealthCheckResult(
        service_name=service_name,
        port=port,
        http_status=http_status,
        body=body,
        passed=passed,
        output=output,
    )


# ---------------------------------------------------------------------------
# Smoke test helpers
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_VALID_JOB_STATUSES = {"starting", "pending", "running", "completed", "failed"}


def is_valid_job_status(status: str) -> bool:
    """Return True iff *status* is one of the recognised job status values."""
    return status in _VALID_JOB_STATUSES


def parse_generate_response(post_status: int, post_body: str) -> SmokeTestResult:
    """Parse the POST /generate response and return a :class:`SmokeTestResult`.

    ``passed`` is True iff *post_status* == 200 AND the response body contains
    a ``job_id`` field that matches UUID format.

    On non-200 responses the ``failure_reason`` contains *post_status* and
    *post_body*.
    """
    job_id: Optional[str] = None
    failure_reason: Optional[str] = None

    if post_status != 200:
        failure_reason = (
            f"POST /generate returned HTTP {post_status}: {post_body}"
        )
        return SmokeTestResult(
            job_id=None,
            post_status=post_status,
            post_body=post_body,
            job_status=None,
            passed=False,
            failure_reason=failure_reason,
        )

    # Try to extract job_id from JSON body
    try:
        data = json.loads(post_body)
        job_id = data.get("job_id")
    except (json.JSONDecodeError, AttributeError):
        job_id = None

    if job_id is None:
        failure_reason = (
            f"POST /generate returned HTTP 200 but job_id is missing. "
            f"Body: {post_body}"
        )
        passed = False
    elif not _UUID_RE.match(str(job_id)):
        failure_reason = (
            f"POST /generate returned HTTP 200 but job_id is not a valid UUID: "
            f"{job_id!r}"
        )
        passed = False
        job_id = str(job_id)
    else:
        passed = True
        job_id = str(job_id)

    return SmokeTestResult(
        job_id=job_id,
        post_status=post_status,
        post_body=post_body,
        job_status=None,
        passed=passed,
        failure_reason=failure_reason,
    )


def validate_smoke_test(
    post_status: int,
    post_body: str,
    get_status_value: str,
) -> SmokeTestResult:
    """Full smoke test predicate.

    Calls :func:`parse_generate_response` first, then additionally checks
    :func:`is_valid_job_status` on *get_status_value*.

    ``passed`` is True iff:
    - *post_status* == 200
    - *job_id* is a valid UUID
    - *get_status_value* is in the valid job status set
    """
    result = parse_generate_response(post_status, post_body)

    if not result.passed:
        # Already failed at the POST stage; preserve that result
        return result

    # POST stage passed — now validate the job status from the GET response
    if not is_valid_job_status(get_status_value):
        return SmokeTestResult(
            job_id=result.job_id,
            post_status=post_status,
            post_body=post_body,
            job_status=get_status_value,
            passed=False,
            failure_reason=(
                f"GET /job/{{job_id}} returned unexpected status: "
                f"{get_status_value!r}. "
                f"Expected one of: {sorted(_VALID_JOB_STATUSES)}"
            ),
        )

    return SmokeTestResult(
        job_id=result.job_id,
        post_status=post_status,
        post_body=post_body,
        job_status=get_status_value,
        passed=True,
        failure_reason=None,
    )
