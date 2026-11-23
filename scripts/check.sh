#!/usr/bin/env bash
# Developer checks at three depths (dev path only; the user path is `uv run sgw ...`, K20).
#   quick  forbidden paths, ruff, mypy, fast pytest, web lint/typecheck/test             (about 1 minute)
#   full   quick + slow tests, contracts, policy tests, image context, licence gate
#   merge  full + secret scan, new skip markers, test counts per area vs main, demo smoke
# Usage: scripts/check.sh <quick|full|merge>
# Env: CHECK_WORKERS (2), CHECK_BASE (main), SGW_ALLOW_TEST_DROP, SGW_SKIP_DEMO_SMOKE=1, CHECK_VERBOSE=1
#      CI=1 makes merge fail when database tests were skipped for a missing SGW_TEST_DATABASE_URL
# Exit status: number of failed steps. A SKIP is printed with its reason and never counts as a pass.
set -uo pipefail

mode="${1:-quick}"
case "$mode" in quick|full|merge) ;; *) echo "usage: $0 <quick|full|merge>" >&2; exit 2 ;; esac
root="$(git rev-parse --show-toplevel)" || exit 2
cd "$root" || exit 2
workers="${CHECK_WORKERS:-2}"
logs="$(mktemp -d "${TMPDIR:-/tmp}/sgw-check.XXXXXX")"
trap 'rm -rf "$logs"' EXIT
failed=0
skipped=0
started_all=$SECONDS

step() {
  local name="$1" hint="$2"; shift 2
  local started=$SECONDS log="$logs/$name.log" status
  "$@" >"$log" 2>&1
  status=$?
  if (( status == 0 )); then
    printf 'PASS  %-18s %3ss\n' "$name" "$((SECONDS - started))"
    [[ "${CHECK_VERBOSE:-0}" == 1 ]] && sed 's/^/      /' "$log"
  else
    printf 'FAIL  %-18s %3ss  exit %s\n' "$name" "$((SECONDS - started))" "$status"
    tail -n 40 "$log" | sed 's/^/      /'
    printf '      fix: %s\n' "$hint"
    failed=$((failed + 1))
  fi
  return 0
}
skip() { printf 'SKIP  %-18s       %s\n' "$1" "$2"; skipped=$((skipped + 1)); }
has_make_target() { [[ -f Makefile ]] && make -n "$1" >/dev/null 2>&1; }
guard() { uv run --frozen python scripts/guards.py "$@"; }

existing() { local d; for d in "$@"; do [[ -e "$d" ]] && printf '%s\n' "$d"; done; }

python_checks() {
  if [[ ! -f pyproject.toml ]]; then skip python "no pyproject.toml"; return; fi
  step ruff-check "uv run ruff check --fix ." uv run --frozen ruff check .
  step ruff-format "uv run ruff format ." uv run --frozen ruff format --check .
  local strict=()
  while IFS= read -r d; do strict+=("$d"); done < <(existing src/sgw/contracts src/sgw/common src/sgw/approval)
  if (( ${#strict[@]} )); then
    step mypy-strict "fix the reported types; run: uv run mypy --strict ${strict[*]}" \
      uv run --frozen mypy --strict "${strict[@]}"
  else
    skip mypy-strict "no src/sgw/{contracts,common,approval} yet"
  fi
  local targets=()
  while IFS= read -r d; do targets+=("$d"); done < <(existing tests scripts/tests)
  if (( ! ${#targets[@]} )); then skip pytest "no tests/ or scripts/tests/"; return; fi
  local args=(-q -rs -p no:cacheprovider -n "$workers")
  [[ "$mode" == quick ]] && args+=(-m "not slow")
  step pytest "rerun the failing test: uv run pytest <nodeid> -x" pytest_run "${args[@]}" "${targets[@]}"
}

pytest_run() {
  uv run --frozen pytest "$@"
  local status=$?
  (( status == 5 )) && { echo "no tests collected"; return 0; }
  return "$status"
}

web_checks() {
  if [[ ! -f package.json ]]; then skip web "no package.json"; return; fi
  if [[ ! -d node_modules ]]; then
    step web-install "pnpm install --frozen-lockfile" false
    return
  fi
  step web-lint "pnpm -C web exec biome check --write ." pnpm -r --if-present run lint
  step web-typecheck "fix the reported types; run: pnpm -r run typecheck" pnpm -r --if-present run typecheck
  if [[ -n "$(git ls-files 'web/*.test.*' 'web/*.spec.*')" ]]; then
    step web-test "rerun: pnpm -C web exec vitest run <file>" pnpm -r --if-present run test
  else
    skip web-test "no web test files yet"
  fi
}

deep_checks() {
  if [[ -f scripts/export-contracts.py ]]; then
    step contracts "uv run python scripts/export-contracts.py, then commit the generated files" \
      uv run --frozen python scripts/export-contracts.py --check
  elif has_make_target contracts-check; then
    step contracts "make contracts, then commit the generated files" make contracts-check
  else
    skip contracts "no contract export yet"
  fi
  if has_make_target policy-test; then
    step policy-test "make policy-test and fix the failing rego test" make policy-test
  else
    skip policy-test "no policy-test target yet"
  fi
  if docker info >/dev/null 2>&1; then
    step image-context "add the leaked path to .dockerignore" scripts/check-image-context.sh
  else
    skip image-context "Docker not running"
  fi
  step licences "replace the dependency or ask for an allowlist entry" uv run --frozen python scripts/licences.py --strict-unknown
}

ci_mode() { [[ -n "${CI:-}" && "${CI}" != 0 && "${CI}" != false ]]; }

db_tests_ran() {
  if [[ -z "${SGW_TEST_DATABASE_URL:-}" ]]; then
    echo "CI is set but SGW_TEST_DATABASE_URL is not: every database test was skipped"
    return 1
  fi
  if [[ ! -f "$logs/pytest.log" ]]; then
    echo "pytest did not run, so the database tests did not run"
    return 1
  fi
  if grep -E 'SKIPPED.*SGW_TEST_DATABASE_URL' "$logs/pytest.log"; then
    echo "the tests above were skipped for a missing database URL"
    return 1
  fi
}

merge_checks() {
  if ci_mode; then
    step db-tests-ran "export SGW_TEST_DATABASE_URL (CI: scripts/ci_db_setup.py prepares the server)" db_tests_ran
  fi
  step secrets-history "rewrite the commit that holds the secret and rotate the secret" scripts/secret-scan.sh history
  step secrets-staged "unstage the file: git restore --staged <file>" scripts/secret-scan.sh staged
  step skip-markers "remove the marker or add 'sgw-allow-skip: <reason>'" guard markers
  step test-counts "restore the removed tests (SGW_ALLOW_TEST_DROP=<area> for moves)" guard test-counts
  step pinned-actions "pin each action to a full commit SHA" guard pinned-actions
  if [[ "${SGW_SKIP_DEMO_SMOKE:-0}" == 1 ]]; then
    skip demo-smoke "SGW_SKIP_DEMO_SMOKE=1"
  elif [[ -x scripts/demo-smoke.sh ]]; then
    step demo-smoke "read out/demo-smoke.json for the failing step" scripts/demo-smoke.sh
  else
    skip demo-smoke "scripts/demo-smoke.sh not written yet"
  fi
}

echo "check.sh $mode in $root"
step forbidden-paths "git rm --cached <path> for each file listed" guard forbidden-paths
python_checks
web_checks
[[ "$mode" != quick ]] && deep_checks
[[ "$mode" == merge ]] && merge_checks
if ! git config --get core.hooksPath >/dev/null && [[ ! -f "$(git rev-parse --git-common-dir)/hooks/pre-commit" ]]; then
  echo "note  git hooks are not installed. Run: make hooks"
fi
echo "check.sh $mode: $failed failed, $skipped skipped, $((SECONDS - started_all))s"
exit "$failed"
