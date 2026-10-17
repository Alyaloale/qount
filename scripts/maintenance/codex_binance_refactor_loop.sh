#!/usr/bin/env bash
set -euo pipefail

# Iterative local Codex refactor loop for the Binance personal system.
# Each round has an implementer, an independent reviewer, and a correction writer.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_ROOT="${QOUNT_CODEX_REFACTOR_LOG_ROOT:-$ROOT_DIR/state/codex_refactor}"
MAX_ROUNDS="${QOUNT_CODEX_REFACTOR_ROUNDS:-8}"
START_ROUND="${QOUNT_CODEX_REFACTOR_START_ROUND:-1}"
MODEL="${QOUNT_CODEX_REFACTOR_MODEL:-gpt-6.1-sol}"
REASONING="${QOUNT_CODEX_REFACTOR_REASONING:-high}"
PAUSE_BETWEEN_ROUNDS="${QOUNT_CODEX_REFACTOR_PAUSE:-0}"

usage() {
  cat <<'EOF'
Usage: scripts/maintenance/codex_binance_refactor_loop.sh [options]

Options:
  --rounds N       Maximum implementation rounds (default: 8)
  --start N        Start at round N without overwriting earlier reports (default: 1)
  --pause          Pause after each round for a human correction file
  --log-root PATH  Store round reports under PATH
  --help           Show this help

The loop uses the local Codex CLI with gpt-6.1-sol/high. It never enables real
orders and never resets or cleans unrelated user changes.
EOF
}

while (($#)); do
  case "$1" in
    --rounds)
      MAX_ROUNDS="$2"
      shift 2
      ;;
    --start)
      START_ROUND="$2"
      shift 2
      ;;
    --pause)
      PAUSE_BETWEEN_ROUNDS=1
      shift
      ;;
    --log-root)
      LOG_ROOT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI is required" >&2
  exit 1
fi
if ! [[ "$MAX_ROUNDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "--rounds must be a positive integer" >&2
  exit 2
fi
if ! [[ "$START_ROUND" =~ ^[1-9][0-9]*$ ]] || ((START_ROUND > MAX_ROUNDS)); then
  echo "--start must be a positive round not greater than --rounds" >&2
  exit 2
fi

mkdir -p "$LOG_ROOT"
cd "$ROOT_DIR"

BASELINE="$LOG_ROOT/baseline-$(date -u +%Y%m%dT%H%M%SZ).txt"
git status --short >"$BASELINE"

common_prompt() {
  cat <<'EOF'
You are refactoring the QOUNT repository into a small, readable personal Binance trading system.

Authoritative scope:
- Binance USD-M is the only live venue in this phase.
- Use one shared Binance asset mapping for research, account data, signals, orders and UI.
- The paper page is forward research only and must show Binance-compatible lines only.
- Run only lines that need fresh forward observations; archived or failed lines stay hidden.
- Keep the existing FastAPI/static frontend shape and reuse existing account observers, SQLite data,
  research artifacts, execution contracts and ledger code where they are actually compatible.
- The real trading engine must remain small but support signal -> order plan -> optional confirmation ->
  order -> fill -> account record, with idempotency, exchange-rule checks, fill polling and restart state.
- orders_authorized must remain false unless an explicit owner authorization already exists. Never place a
  real order, enable a production timer, or move credentials.

Do not build microservices, a generic experiment platform, a data warehouse, a strategy registry, a
portfolio optimizer, a new notification platform, or a new governance process.

Clean up obsolete duplicate code and documents only after searching references. Delete confirmed dead
files instead of adding compatibility wrappers. Preserve docs/current.md, AGENTS.md, credentials, active
Binance research inputs, current tests, and unrelated user changes. Do not use git reset, git checkout,
or broad destructive cleanup.

Before editing, inspect the relevant code and current git state. Make a small cohesive change, run focused
checks, and finish with a concrete report containing:
1. changed files and why;
2. deleted files and the reference search that justified deletion;
3. tests/checks actually run and results;
4. remaining gaps and the next smallest useful change.
Never claim a feature is complete if it is only documented.

Keep each round narrow. Start with the files named by the previous correction and their direct callers;
do not scan or rewrite docs/archive, state artifacts, legacy strategy trees, or unrelated research files
unless a reference search proves they are part of the blocker. A round should finish in minutes, not
become a repository-wide audit.
EOF
}

run_codex() {
  local prompt_file="$1"
  local output_file="$2"
  codex exec \
    --model "$MODEL" \
    --config "model_reasoning_effort=$REASONING" \
    --config 'approval_policy="never"' \
    --cd "$ROOT_DIR" \
    --sandbox danger-full-access \
    --color never \
    --output-last-message "$output_file" \
    - <"$prompt_file" >"${output_file%.md}.events.jsonl" 2>&1
}

for ((round=START_ROUND; round<=MAX_ROUNDS; round++)); do
  ROUND_DIR="$LOG_ROOT/round-$(printf '%02d' "$round")"
  mkdir -p "$ROUND_DIR"

  if [[ -s "$ROUND_DIR/implementation.md" && -s "$ROUND_DIR/review.md" && -s "$ROUND_DIR/correction.md" ]]; then
    echo "[codex-refactor] round $round already has reports; use --start $((round + 1)) to continue"
    continue
  fi

  previous_correction=""
  if ((round > 1)); then
    previous_dir="$LOG_ROOT/round-$(printf '%02d' "$((round-1))")"
    if [[ -s "$previous_dir/correction.md" ]]; then
      previous_correction="$(cat "$previous_dir/correction.md")"
    else
      previous_correction="Resume from the incomplete previous round. Inspect its event log and current diff before editing."
    fi
  fi
  manual_correction=""
  if [[ -n "${QOUNT_CODEX_CORRECTION_FILE:-}" && -f "$QOUNT_CODEX_CORRECTION_FILE" ]]; then
    manual_correction="$(cat "$QOUNT_CODEX_CORRECTION_FILE")"
  fi

  {
    common_prompt
    cat <<EOF

This is implementation round $round of $MAX_ROUNDS.
Read docs/personal-system-consolidation-plan.md and implement the highest-value outstanding part of
that plan. Prefer existing modules over new abstractions. The current worktree may contain user changes;
work with them and do not revert them.

Previous round correction:
${previous_correction:-none}

Additional owner correction:
${manual_correction:-none}
EOF
  } >"$ROUND_DIR/implement.prompt"

  echo "[codex-refactor] round $round: implementation"
  run_codex "$ROUND_DIR/implement.prompt" "$ROUND_DIR/implementation.md"

  {
    common_prompt
    cat <<EOF

Act as an independent reviewer for implementation round $round. Do not edit files.
Read the implementation report at $ROUND_DIR/implementation.md and inspect the actual diff and code.
Check these concrete outcomes:
- Binance-only asset identity is consistent across research, paper/forward, account and execution.
- The paper page cannot show non-Binance or archived lines as active forward research.
- Real account records are not confused with paper_* data or a different pilot ledger.
- Signal, order intent, exchange order, fill, fees/funding and account records can be traced where implemented.
- Frontend is read-only for data and does not invent PnL; backend owns data and execution.
- No real order authority, production timer, credential movement, or future-data shortcut was introduced.
- Dead duplicate code/docs removed only when references are absent.
- Tests and checks support the claimed change.

Return a concise review with sections: BLOCKERS, REQUIRED_FIXES, OPTIONAL_CLEANUP, VERIFIED.
Use BLOCKERS: none when there are no blockers. Do not edit the repository.
EOF
  } >"$ROUND_DIR/review.prompt"

  echo "[codex-refactor] round $round: review"
  run_codex "$ROUND_DIR/review.prompt" "$ROUND_DIR/review.md"

  {
    common_prompt
    cat <<EOF

Act as the correction writer for implementation round $round. Do not edit files.
Read the implementation report and independent review:
- $ROUND_DIR/implementation.md
- $ROUND_DIR/review.md

Convert the findings into the next implementation instruction. Keep it short and ordered by impact.
If the review is clean, write exactly: REFACTOR_READY
Otherwise write sections: MUST_FIX, SHOULD_FIX, DO_NOT_TOUCH, VERIFICATION.
Do not invent work outside the Binance personal-system scope.
EOF
  } >"$ROUND_DIR/correction.prompt"

  echo "[codex-refactor] round $round: correction synthesis"
  run_codex "$ROUND_DIR/correction.prompt" "$ROUND_DIR/correction.md"

  git diff --check >"$ROUND_DIR/diff-check.txt" 2>&1 || true
  git status --short >"$ROUND_DIR/status.txt"

  if grep -q '^REFACTOR_READY$' "$ROUND_DIR/correction.md"; then
    echo "[codex-refactor] review ready after round $round"
    exit 0
  fi

  if [[ "$PAUSE_BETWEEN_ROUNDS" == "1" ]]; then
    echo "[codex-refactor] inspect $ROUND_DIR and press Enter for the next round"
    read -r
  fi
done

echo "[codex-refactor] maximum rounds reached; inspect $LOG_ROOT" >&2
exit 3
