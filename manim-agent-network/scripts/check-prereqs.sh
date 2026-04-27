#!/usr/bin/env bash

PASS=0
FAIL=1
overall=0

check_tool() {
    local name="$1"
    local min_major="$2"
    local min_minor="$3"
    local version_cmd="$4"
    local install_url="$5"

    local raw_version
    if ! raw_version=$(eval "$version_cmd" 2>/dev/null); then
        echo "✗ $name — not found. Install from: $install_url"
        return $FAIL
    fi

    local version_str
    version_str=$(echo "$raw_version" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)

    if [[ -z "$version_str" ]]; then
        echo "✗ $name — could not parse version from: $raw_version. Install from: $install_url"
        return $FAIL
    fi

    local major minor
    major=$(echo "$version_str" | cut -d. -f1)
    minor=$(echo "$version_str" | cut -d. -f2)

    if (( major > min_major )) || (( major == min_major && minor >= min_minor )); then
        echo "✓ $name $version_str"
        return $PASS
    else
        echo "✗ $name $version_str — required >= ${min_major}.${min_minor}. Install from: $install_url"
        return $FAIL
    fi
}

check_tool "Docker Engine" 20 10 "docker --version" "https://docs.docker.com/engine/install/" || overall=1
check_tool "Docker Compose" 2 0 "docker compose version" "https://docs.docker.com/compose/install/" || overall=1
check_tool "Git" 2 0 "git --version" "https://git-scm.com/downloads" || overall=1

if [[ $overall -eq 0 ]]; then
    echo "✓ All prerequisites satisfied."
fi

exit $overall
