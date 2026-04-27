#!/usr/bin/env bash

# validate.sh — Health checks and smoke test for Manim Agent Network
# Usage:
#   ./scripts/validate.sh [--health-only | --smoke]
#   Default: --health-only

set -euo pipefail

# ─── Services ────────────────────────────────────────────────────────────────
declare -a SERVICE_NAMES=("orchestrator" "script-writer" "code-generator" "validator" "voiceover" "compositor" "image-fetcher")
declare -a SERVICE_PORTS=(8000 8001 8002 8003 8004 8005 8006)

# ─── Health Check ─────────────────────────────────────────────────────────────
health_check() {
    local name="$1"
    local port="$2"

    local http_status
    http_status=$(curl -s -o /tmp/body -w "%{http_code}" "http://localhost:${port}/health")
    local body
    body=$(cat /tmp/body)

    if [[ "$http_status" == "200" && "$body" == '{"status":"ok"}' ]]; then
        echo "✓ ${name} (port ${port}) is healthy"
        return 0
    else
        echo "✗ ${name} (port ${port}) — HTTP ${http_status} — body: ${body}"
        return 1
    fi
}

# ─── Smoke Test ───────────────────────────────────────────────────────────────
smoke_test() {
    local failures=0

    echo ""
    echo "Running smoke test..."

    # POST /generate
    local post_status
    post_status=$(curl -s -o /tmp/smoke_body -w "%{http_code}" \
        -X POST "http://localhost:8000/generate" \
        -H "Content-Type: application/json" \
        -d '{"topic": "The Pythagorean Theorem visually explained"}')
    local post_body
    post_body=$(cat /tmp/smoke_body)

    if [[ "$post_status" != "200" ]]; then
        echo "✗ SMOKE FAIL: POST /generate returned ${post_status}: ${post_body}"
        return 1
    fi

    # Parse job_id
    local job_id
    job_id=$(echo "$post_body" | jq -r .job_id 2>/dev/null || true)

    local uuid_regex='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if [[ -z "$job_id" || "$job_id" == "null" ]] || ! [[ "$job_id" =~ $uuid_regex ]]; then
        echo "✗ SMOKE FAIL: job_id missing or invalid in response: ${post_body}"
        return 1
    fi

    echo "✓ Job submitted: ${job_id}"

    # Wait for job to register
    sleep 2

    # GET /job/{job_id}
    local get_status
    get_status=$(curl -s -o /tmp/job_body -w "%{http_code}" \
        "http://localhost:8000/job/${job_id}")
    local job_body
    job_body=$(cat /tmp/job_body)

    if [[ "$get_status" != "200" ]]; then
        echo "✗ SMOKE FAIL: GET /job/${job_id} returned ${get_status}: ${job_body}"
        return 1
    fi

    local job_status
    job_status=$(echo "$job_body" | jq -r .status 2>/dev/null || true)

    case "$job_status" in
        starting|pending|running|completed|failed)
            echo "✓ Job status: ${job_status}"
            ;;
        *)
            echo "✗ SMOKE FAIL: unexpected status '${job_status}'"
            return 1
            ;;
    esac

    return 0
}

# ─── Main ─────────────────────────────────────────────────────────────────────
main() {
    local mode="${1:---health-only}"
    local failures=0

    echo "Running health checks..."
    echo ""

    for i in "${!SERVICE_NAMES[@]}"; do
        health_check "${SERVICE_NAMES[$i]}" "${SERVICE_PORTS[$i]}" || (( failures++ )) || true
    done

    if [[ "$mode" == "--smoke" ]]; then
        smoke_test || (( failures++ )) || true
    fi

    echo ""
    if [[ $failures -gt 0 ]]; then
        exit 1
    fi

    echo "✓ All checks passed. System is ready."
    exit 0
}

main "$@"
