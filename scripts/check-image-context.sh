#!/usr/bin/env bash
# Proves that every Docker build context, filtered by its ignore file, holds no private or local-only files:
# the root .dockerignore and each docker/<image>/Dockerfile.dockerignore (BuildKit reads the ignore file that
# sits next to the Dockerfile). BuildKit exports a FROM-scratch copy of each context to a temp dir: no base
# image pull, no image left behind.
# Usage: scripts/check-image-context.sh [context-dir]    exit 0 clean, 1 leak, 2 tool error
set -uo pipefail

root="$(git rev-parse --show-toplevel)"
context="${1:-$root}"
if ! docker info >/dev/null 2>&1; then
  echo "check-image-context: Docker is not running. Fix: start Docker Desktop (or run in CI)." >&2
  exit 2
fi
work="$(mktemp -d "${TMPDIR:-/tmp}/sgw-ctx.XXXXXX")"
trap 'rm -rf "$work"' EXIT

status=0
check() {
  local label="$1" ignore="$2" dir="$work/$3"
  mkdir -p "$dir/df" "$dir/out"
  printf 'FROM scratch\nCOPY . /ctx\n' > "$dir/df/Dockerfile"
  if [[ -n "$ignore" ]]; then cp "$ignore" "$dir/df/Dockerfile.dockerignore"; fi
  if ! DOCKER_BUILDKIT=1 docker build -q -f "$dir/df/Dockerfile" --output "type=local,dest=$dir/out" "$context" >/dev/null; then
    echo "check-image-context: docker build of the $label context failed" >&2
    status=2
    return
  fi
  local leaks files size
  leaks="$(cd "$dir/out/ctx" && find . \( -name '.env' -o -name '.env.*' -o -name '.git' \
    -o -path './raw' -o -name 'node_modules' -o -name '.venv' -o -path './var' \) -print | sed 's|^\./||')"
  files="$(find "$dir/out/ctx" -type f | wc -l | tr -d ' ')"
  size="$(du -sk "$dir/out/ctx" | cut -f1)"
  if [[ -n "$leaks" ]]; then
    echo "check-image-context: FAIL, the $label build context contains:"
    printf '  %s\n' $leaks
    echo "  Fix: exclude the path in ${ignore:-.dockerignore}"
    [[ $status -eq 0 ]] && status=1
    return
  fi
  echo "check-image-context: PASS $label ($files files, ${size} KiB in context)"
}

check "root" "" root
for ignore in "$root"/docker/*/Dockerfile.dockerignore; do
  [[ -f "$ignore" ]] || continue
  name="$(basename "$(dirname "$ignore")")"
  check "docker/$name" "$ignore" "$name"
done
exit $status
