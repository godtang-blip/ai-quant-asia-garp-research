#!/usr/bin/env bash
set -euo pipefail

[[ "$GARP_CYCLE" =~ ^[1-9][0-9]{0,19}$ ]]
[[ "$GARP_CYCLE_ARTIFACTS" == 1 ]]
[[ "${GITHUB_RUN_ATTEMPT:-1}" == 1 ]] || { echo "Start a new dispatch to restore this cycle."; exit 2; }
if [[ "$GARP_CYCLE_MODE" == batch ]]; then
  [[ "$GARP_CYCLE_EXPLICIT" == true ]]
  [[ "$GARP_CYCLE_DAILY_BUDGET" =~ ^[1-9][0-9]{0,4}$ ]]
fi

mkdir -p cycle-working/plan cycle-working/state
gh run download "$GARP_CYCLE" --name "garp-cycle-$GARP_CYCLE-plan" --dir cycle-working/plan
jq -e --arg expected "$GARP_CYCLE" '.cycle_id == $expected' cycle-working/plan/plan.json >/dev/null
# Use repository-scoped artifact IDs. A failed scan aborts the dispatch rather than
# silently treating an unavailable checkpoint as an empty cycle.
catalog="$(mktemp "$RUNNER_TEMP/garp-artifacts.XXXXXX")"
gh api --paginate "repos/$GITHUB_REPOSITORY/actions/artifacts?per_page=100" \
  --jq ".artifacts[] | select(.expired == false and (.name | startswith(\"garp-cycle-$GARP_CYCLE-\"))) |
  [.name, .workflow_run.id, .created_at, .id] | @tsv" > "$catalog"

latest="$(awk -v stem="garp-cycle-$GARP_CYCLE-state-" 'index($1,stem)==1' "$catalog" | sort -k3,3 -k4,4n | tail -1)"
cutoff=''
if [[ -n "$latest" ]]; then
  IFS=$'\t' read -r name run cutoff _ <<< "$latest"
  gh run download "$run" --name "$name" --dir "$RUNNER_TEMP/garp-cycle-rollup"
  python -m src.research_cycle restore --plan cycle-working/plan --state cycle-working/state \
    --input "$RUNNER_TEMP/garp-cycle-rollup"
fi

while IFS=$'\t' read -r name run created id; do
  if [[ "$name" == "garp-cycle-$GARP_CYCLE-shard-"* && ( -z "$cutoff" || "$created" > "$cutoff" || "$created" == "$cutoff" ) ]]; then
    gh run download "$run" --name "$name" --dir "$RUNNER_TEMP/garp-cycle-shards/$id"
  fi
done < "$catalog"
mkdir -p "$RUNNER_TEMP/garp-cycle-shards"
python -m src.research_cycle restore --plan cycle-working/plan --state cycle-working/state \
  --input "$RUNNER_TEMP/garp-cycle-shards"

day="$(date -u +%Y-%m-%d)"
reserved=0
while IFS=$'\t' read -r name _; do
  prefix="garp-cycle-$GARP_CYCLE-quota-$day-"
  if [[ "$name" == "$prefix"* ]]; then
    value="${name#"$prefix"}"
    value="${value%%-*}"
    [[ "$value" =~ ^[1-9][0-9]{0,4}$ ]]
    reserved=$((reserved + value))
  fi
done < "$catalog"
jobs='[]'
if [[ "$GARP_CYCLE_MODE" == batch ]]; then
  market=()
  if [[ "$GARP_CYCLE_MARKET" != All ]]; then market=(--market "$GARP_CYCLE_MARKET"); fi
  jobs="$(python -m src.research_cycle dispatch --plan cycle-working/plan --state cycle-working/state \
    --max-shards "$GARP_CYCLE_MAX_SHARDS" --budget "$GARP_CYCLE_JOB_BUDGET" \
    --daily-budget "$GARP_CYCLE_DAILY_BUDGET" --reserved "$reserved" "${market[@]}")"
fi
jq -cn --argjson items "$jobs" --arg day "$day" '{items:$items, date:$day}' > cycle-quota.json
{
  printf 'matrix=%s\n' "$(jq -c '{include:.items}' cycle-quota.json)"
  printf 'jobs=%s\n' "$(jq '.items | length' cycle-quota.json)"
  printf 'reserved=%s\n' "$(jq '[.items[].budget] | add // 0' cycle-quota.json)"
  printf 'quota_date=%s\n' "$day"
  printf 'provider_version=%s\n' "$(jq -er '.provider_version' cycle-working/plan/plan.json)"
} >> "$GITHUB_OUTPUT"
