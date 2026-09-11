#!/usr/bin/env bash
# Builds the index and copies it where the site can read it.
# Invented for the test suite; it touches nothing real.
set -euo pipefail

source ./lib/logging.sh

# Writes one line to the build log.
log_step() {
    printf '%s\n' "$1"
}

build_index() {
    log_step "building"
    extractium build --config config.yaml
}

build_index
