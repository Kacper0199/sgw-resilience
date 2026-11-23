#!/usr/bin/env bash
# Dev script (K20: the user path is `uv run sgw demo smoke`): the ten PS-17 story steps on a scratch database
# and a private replay stack, model-provenance asserts, the replay hit rate and K19 playback with the gateway
# stopped. Report: out/demo-smoke.json. Exit status: number of failures (0 = green).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
exec uv run --frozen sgw demo smoke --out out/demo-smoke.json "$@"
