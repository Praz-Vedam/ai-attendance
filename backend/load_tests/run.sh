#!/usr/bin/env bash
# Run Locust throughput test (polling + mark burst + teacher).
# Forwards to run_throughput_test.sh; pass extra locust flags after -- if needed.
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/run_throughput_test.sh" "$@"
