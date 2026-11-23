#!/usr/bin/env bash
# Secret scan with gitleaks: the host binary when installed, else the image pinned by digest.
# Usage: scripts/secret-scan.sh staged            staged changes (pre-commit)
#        scripts/secret-scan.sh history [range]   commits reachable from HEAD, or a git log range
#        scripts/secret-scan.sh dir <path>        files under a directory, no git
# Exit 0 clean, 1 leak found, 2 usage or tool error. Findings are always redacted.
set -uo pipefail

GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks@sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854"

mode="${1:-}"
root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "secret-scan: not inside a git repository" >&2; exit 2; }
common="$(git rev-parse --path-format=absolute --git-common-dir)"
config="$root/.gitleaks.toml"

case "$mode" in
  staged) args=(git --staged) ;;
  history) args=(git); [[ -n "${2:-}" ]] && args+=("--log-opts=$2") ;;
  dir) [[ -n "${2:-}" ]] || { echo "usage: $0 dir <path>" >&2; exit 2; }; args=(dir "$(cd "$2" && pwd)") ;;
  *) echo "usage: $0 <staged|history [range]|dir <path>>" >&2; exit 2 ;;
esac
[[ "$mode" != dir ]] && args+=("$root")
args+=(--config "$config" --redact --verbose --no-banner --exit-code 1 --log-level warn)

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks "${args[@]}"
  exit $?
fi
if ! docker info >/dev/null 2>&1; then
  echo "secret-scan: neither gitleaks nor a running Docker found. Fix: brew install gitleaks, or start Docker Desktop." >&2
  exit 2
fi
mounts=(-v "$root:$root" -v "$common:$common")
[[ "$mode" == dir ]] && mounts+=(-v "${args[1]}:${args[1]}:ro")
docker run --rm --user "$(id -u):$(id -g)" "${mounts[@]}" -w "$root" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
  "$GITLEAKS_IMAGE" "${args[@]}"
