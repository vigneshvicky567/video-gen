"""
Property-based tests for the project-init feature.

Uses Hypothesis to validate correctness properties defined in the design document.
"""

import json
import pytest
from pathlib import Path
from dataclasses import dataclass
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.init_helpers import (
    parse_semver, version_gte, check_env_key,
    parse_health_response, validate_smoke_test
)


# ---------------------------------------------------------------------------
# Property 1: Version comparison correctness
# Feature: project-init, Property 1: Version comparison correctness
# Validates: Requirements 1.1, 1.2, 1.3
# ---------------------------------------------------------------------------

@given(
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
)
@settings(max_examples=100)
def test_version_gte_matches_tuple_comparison(major_a, minor_a, major_b, minor_b):
    """version_gte must agree with Python tuple comparison for all (major, minor) pairs."""
    # Feature: project-init, Property 1: Version comparison correctness
    assert version_gte((major_a, minor_a), (major_b, minor_b)) == (
        (major_a, minor_a) >= (major_b, minor_b)
    )


# Strategy for optional pre-release suffixes
_prerelease_suffix = st.one_of(
    st.just(""),
    st.just("-beta"),
    st.just("-rc1"),
    st.just(".pre"),
)


@given(
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    _prerelease_suffix,
    st.sampled_from(["docker", "git", "compose"]),
)
@settings(max_examples=100)
def test_parse_semver_extracts_correct_tuple(major, minor, patch, suffix, tool):
    """parse_semver must extract the correct (major, minor, patch) from realistic version strings."""
    # Feature: project-init, Property 1: Version comparison correctness
    if tool == "docker":
        version_str = f"Docker version {major}.{minor}.{patch}{suffix}, build abc1234"
    elif tool == "git":
        version_str = f"git version {major}.{minor}.{patch}{suffix}"
    else:  # compose
        version_str = f"Docker Compose version v{major}.{minor}.{patch}{suffix}"

    result = parse_semver(version_str)
    assert result == (major, minor, patch), (
        f"Expected ({major}, {minor}, {patch}), got {result} from {version_str!r}"
    )


# ---------------------------------------------------------------------------
# Property 2: Prerequisite check result correctness and output completeness
# Feature: project-init, Property 2: Prerequisite check result correctness and output completeness
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
# ---------------------------------------------------------------------------

@dataclass
class VersionCheckResult:
    tool_name: str
    passed: bool
    output: str


# Tool configuration: name -> (min_version, install_url)
_TOOL_CONFIG = {
    "Docker Engine": ((20, 10), "https://docs.docker.com/engine/install/"),
    "Docker Compose": ((2, 0), "https://docs.docker.com/compose/install/"),
    "Git": ((2, 0), "https://git-scm.com/downloads"),
}


def check_prerequisites(
    tool_states: dict,
) -> list:
    """
    Helper that takes a dict of {tool_name: (is_present: bool, version: tuple[int,int])}
    and returns a list of VersionCheckResult.

    Minimum versions:
      - Docker Engine: (20, 10)
      - Docker Compose: (2, 0)
      - Git: (2, 0)
    """
    results = []
    for tool_name, (min_version, install_url) in _TOOL_CONFIG.items():
        is_present, detected_version = tool_states[tool_name]
        passed = is_present and version_gte(detected_version, min_version)

        if passed:
            output = (
                f"✓ {tool_name} {detected_version[0]}.{detected_version[1]} — OK"
            )
        else:
            required_str = f"{min_version[0]}.{min_version[1]}"
            output = (
                f"FAIL: {tool_name} — "
                f"required >= {required_str}, "
                f"install: {install_url}"
            )

        results.append(VersionCheckResult(
            tool_name=tool_name,
            passed=passed,
            output=output,
        ))
    return results


@given(
    # Docker Engine
    st.booleans(),
    st.tuples(st.integers(0, 99), st.integers(0, 99)),
    # Docker Compose
    st.booleans(),
    st.tuples(st.integers(0, 99), st.integers(0, 99)),
    # Git
    st.booleans(),
    st.tuples(st.integers(0, 99), st.integers(0, 99)),
)
@settings(max_examples=100)
def test_check_prerequisites_result_correctness(
    docker_present, docker_version,
    compose_present, compose_version,
    git_present, git_version,
):
    """
    For any combination of tool states, check_prerequisites must:
    - Return exactly 3 results
    - Each passed field matches is_present AND version >= minimum
    - Every failing result's output contains tool name, required version, and install URL
    """
    # Feature: project-init, Property 2: Prerequisite check result correctness and output completeness
    tool_states = {
        "Docker Engine": (docker_present, docker_version),
        "Docker Compose": (compose_present, compose_version),
        "Git": (git_present, git_version),
    }

    results = check_prerequisites(tool_states)

    # Must produce exactly 3 results
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    # Validate each result
    for result in results:
        tool_name = result.tool_name
        is_present, version = tool_states[tool_name]
        min_version, install_url = _TOOL_CONFIG[tool_name]

        expected_passed = is_present and version_gte(version, min_version)
        assert result.passed == expected_passed, (
            f"{tool_name}: expected passed={expected_passed}, got {result.passed} "
            f"(is_present={is_present}, version={version}, min={min_version})"
        )

        if not result.passed:
            required_str = f"{min_version[0]}.{min_version[1]}"
            assert tool_name in result.output, (
                f"Failing output for {tool_name} must contain tool name. Got: {result.output!r}"
            )
            assert required_str in result.output, (
                f"Failing output for {tool_name} must contain required version '{required_str}'. "
                f"Got: {result.output!r}"
            )
            assert install_url in result.output, (
                f"Failing output for {tool_name} must contain install URL '{install_url}'. "
                f"Got: {result.output!r}"
            )


# ---------------------------------------------------------------------------
# Property 3: Env template contains all required keys with correct defaults
# Feature: project-init, Property 3: Env template contains all required keys with correct defaults
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9
# NOTE: This is a deterministic parameterized test, not a Hypothesis test.
# ---------------------------------------------------------------------------

_ENV_TEMPLATE_PATH = Path(__file__).parent.parent / ".env.template"

_REQUIRED_ENV_KEYS = [
    ("NVIDIA_API_KEY", "your-nvidia-api-key-here"),
    ("LANGSMITH_API_KEY", "your-langsmith-api-key-here"),
    ("SCRIPT_WRITER_MODEL", "moonshotai/kimi-k2-instruct"),
    ("CODE_GENERATOR_MODEL", "qwen/qwen3-coder-480b-a35b-instruct"),
    ("VOICEOVER_PROVIDER", "kokoro"),
    ("VOICEOVER_FALLBACK_PROVIDER", "espeak"),
    ("ALLOW_ESPEAK_FALLBACK", "true"),
    ("KOKORO_VOICE", "af_sarah"),
]


def _parse_env_template(path: Path) -> dict:
    """Parse a .env template file into a dict of {key: value}."""
    result = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        k = k.strip()
        # Remove inline comments
        if " #" in v:
            v = v[: v.index(" #")]
        result[k] = v.strip()
    return result


@pytest.mark.parametrize("key,expected_default", _REQUIRED_ENV_KEYS)
def test_env_template_contains_required_keys(key, expected_default):
    """
    .env.template must contain every required key with the correct default value.
    Feature: project-init, Property 3: Env template contains all required keys with correct defaults
    """
    assert _ENV_TEMPLATE_PATH.exists(), (
        f".env.template not found at {_ENV_TEMPLATE_PATH}"
    )
    parsed = _parse_env_template(_ENV_TEMPLATE_PATH)
    assert key in parsed, (
        f"Key '{key}' not found in .env.template. Found keys: {list(parsed.keys())}"
    )
    assert parsed[key] == expected_default, (
        f"Key '{key}': expected default '{expected_default}', got '{parsed[key]}'"
    )


# ---------------------------------------------------------------------------
# Property 4: Env guard rejects all invalid NVIDIA_API_KEY states
# Feature: project-init, Property 4: Env guard rejects all invalid NVIDIA_API_KEY states
# Validates: Requirements 3.10
# ---------------------------------------------------------------------------

# Strategy for invalid NVIDIA_API_KEY values
_invalid_key_strategy = st.one_of(
    # Empty string
    st.just("NVIDIA_API_KEY=\n"),
    # Placeholder value
    st.just("NVIDIA_API_KEY=your-nvidia-api-key-here\n"),
    # Whitespace-only value
    st.builds(
        lambda ws: f"NVIDIA_API_KEY={ws}\n",
        st.text(alphabet=" \t\n", min_size=1),
    ),
    # Absent key — env content without NVIDIA_API_KEY line at all
    st.just("OTHER_KEY=value\n"),
)


@given(_invalid_key_strategy)
@settings(max_examples=100)
def test_env_guard_rejects_invalid_nvidia_key(env_content):
    """
    check_env_key must return passed=False for all invalid NVIDIA_API_KEY states:
    empty, placeholder, whitespace-only, or absent.
    Feature: project-init, Property 4: Env guard rejects all invalid NVIDIA_API_KEY states
    """
    result = check_env_key(env_content, "NVIDIA_API_KEY", "your-nvidia-api-key-here")
    assert result.passed is False, (
        f"Expected passed=False for env_content={env_content!r}, got passed={result.passed}"
    )
    assert "NVIDIA_API_KEY" in result.output, (
        f"Expected 'NVIDIA_API_KEY' in output for env_content={env_content!r}. "
        f"Got output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Property 5: Health check result faithfully reflects HTTP response
# Feature: project-init, Property 5: Health check result faithfully reflects HTTP response
# Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
# ---------------------------------------------------------------------------

@given(
    st.integers(100, 599),
    st.text(alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Zs")), max_size=200),
)
@settings(max_examples=100)
def test_health_check_result_faithfulness(http_status, body):
    """
    parse_health_response must set passed=True iff http_status==200 and body=='{"status": "ok"}'.
    For failing results, output must contain service name, port, status code, and body.
    Feature: project-init, Property 5: Health check result faithfully reflects HTTP response
    """
    service_name = "test-service"
    port = 8000

    result = parse_health_response(http_status, body, service_name, port)

    expected_passed = (http_status == 200 and body == '{"status": "ok"}')
    assert result.passed == expected_passed, (
        f"Expected passed={expected_passed} for http_status={http_status}, body={body!r}. "
        f"Got passed={result.passed}"
    )

    if not result.passed:
        assert service_name in result.output, (
            f"Failing output must contain service name '{service_name}'. Got: {result.output!r}"
        )
        assert str(port) in result.output, (
            f"Failing output must contain port '{port}'. Got: {result.output!r}"
        )
        assert str(http_status) in result.output, (
            f"Failing output must contain http_status '{http_status}'. Got: {result.output!r}"
        )
        assert body in result.output, (
            f"Failing output must contain body. Got: {result.output!r}"
        )


# ---------------------------------------------------------------------------
# Property 6: Smoke test response validation
# Feature: project-init, Property 6: Smoke test response validation
# Validates: Requirements 8.2, 8.4, 8.5
# ---------------------------------------------------------------------------

@given(
    st.uuids(),
    st.sampled_from(["starting", "pending", "running", "completed", "failed"]),
)
@settings(max_examples=100)
def test_smoke_test_passes_on_valid_inputs(uuid, job_status):
    """
    validate_smoke_test must return passed=True for valid UUID job_id and valid job status.
    Feature: project-init, Property 6: Smoke test response validation
    """
    post_body = json.dumps({"job_id": str(uuid), "message": "ok"})
    result = validate_smoke_test(200, post_body, job_status)
    assert result.passed is True, (
        f"Expected passed=True for uuid={uuid}, job_status={job_status!r}. "
        f"Got passed={result.passed}, failure_reason={result.failure_reason!r}"
    )


@given(
    st.integers(201, 599),
    st.text(max_size=200),
)
@settings(max_examples=100)
def test_smoke_test_fails_on_non_200(post_status, post_body):
    """
    validate_smoke_test must return passed=False for any non-200 POST status.
    The failure_reason must contain the status code.
    Feature: project-init, Property 6: Smoke test response validation
    """
    result = validate_smoke_test(post_status, post_body, "running")
    assert result.passed is False, (
        f"Expected passed=False for post_status={post_status}. Got passed={result.passed}"
    )
    assert str(post_status) in result.failure_reason, (
        f"Expected str({post_status}) in failure_reason. "
        f"Got failure_reason={result.failure_reason!r}"
    )
