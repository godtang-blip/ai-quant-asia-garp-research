#!/usr/bin/env bash
set -euo pipefail

workflow=run-research-v05.yml
ref="refs/heads/$GITHUB_REF_NAME"
api="repos/$GITHUB_REPOSITORY/actions"
[[ "$GARP_CYCLE" =~ ^[1-9][0-9]{0,19}$ && "$GITHUB_REF" == "$ref" && "${GITHUB_RUN_ATTEMPT:-1}" == 1 ]]

if [[ "$1" == continue ]]; then
  head="$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/$GITHUB_REF_NAME" --jq '.object.sha')"
  [[ "$head" == "$GITHUB_SHA" ]] || {
    echo '::error::Campaign branch changed. The current wave is durable and continuation must use its pinned revision.'
    exit 2
  }
  # GitHub concurrency retains one pending run per group. Avoid replacing an
  # operator's queued dispatch, including a Batch submitted during a wave.
  for status in queued pending waiting requested; do
    others="$(gh api --paginate "$api/workflows/$workflow/runs?status=$status&per_page=100" \
      --jq ".workflow_runs[] | select(.id != $GITHUB_RUN_ID) | .id")"
    if [[ -n "$others" ]]; then
      echo '::error::There is already a pending research workflow. No campaign continuation was dispatched.'
      exit 2
    fi
  done
  jq -cn --arg ref "$GITHUB_REF_NAME" --arg cycle "$GARP_CYCLE" --arg parent "$GITHUB_RUN_ID" '
    {ref:$ref, inputs:{cycle_mode:"autopilot-continue", cycle_state:$cycle, max_symbols:$parent}}' |
    gh api --method POST "$api/workflows/$workflow/dispatches" --input -
  exit
fi

[[ "$1" == restore && "$GARP_CAMPAIGN_CHECKPOINT" =~ ^[1-9][0-9]{0,19}$ ]]
export GARP_CYCLE_MODE=aggregate
export GARP_CYCLE_CATALOG="$RUNNER_TEMP/garp-campaign-artifacts.tsv"
bash .github/scripts/restore-research-cycle.sh

latest_lease="$(awk -v p="garp-cycle-$GARP_CYCLE-campaign-lease-" 'index($1,p)==1' "$GARP_CYCLE_CATALOG" |
  sort -k3,3 -k4,4n | tail -1)"
anchor="$GARP_CAMPAIGN_CHECKPOINT"
run="$(gh api "$api/runs/$anchor")"
jq -e --arg branch "$GITHUB_REF_NAME" --arg path ".github/workflows/$workflow" --arg ref "$ref" \
  '.status == "completed" and .head_branch == $branch and
   (.path == $path or .path == ($path + "@" + $ref)) and .run_attempt == 1' <<< "$run" >/dev/null || {
    echo '::error::Select a completed first-attempt run from this workflow and branch.'
    exit 2
  }

transition="$GARP_CAMPAIGN_MODE"
if [[ "$transition" == full-sweep && -n "$latest_lease" ]]; then
  transition=promote
fi
case "$transition" in
  research-now|full-sweep)
    [[ -z "$latest_lease" ]] || {
      echo '::error::This cycle already has a campaign lease. Use the existing campaign handoff.'
      exit 2
    }
    jq -e '.conclusion == "success"' <<< "$run" >/dev/null
    last_quota="$(awk -v p="garp-cycle-$GARP_CYCLE-quota-" 'index($1,p)==1' "$GARP_CYCLE_CATALOG" |
      sort -k3,3 -k4,4n | tail -1)"
    gh run download "$anchor" --name "garp-cycle-$GARP_CYCLE-state-1" --dir campaign-batch-state
    gh run download "$anchor" --name "garp-cycle-$GARP_CYCLE-report-1" --dir campaign-batch-report
    if [[ -n "$last_quota" ]]; then
      IFS=$'\t' read -r quota quota_run _ <<< "$last_quota"
      [[ "$quota_run" == "$anchor" && "$quota" == *-"$anchor"-1 ]] || {
        echo '::error::Select the latest completed financial Batch for this cycle.'
        exit 2
      }
      gh run download "$anchor" --name "$quota" --dir campaign-batch-quota
      shards="$(jq -er '.items[].shard' campaign-batch-quota/cycle-quota.json)"
    else
      # Quota artifacts expire sooner than financial checkpoints. Identify the
      # original matrix from the completed Batch jobs in that case.
      shards="$(gh api --paginate "$api/runs/$anchor/jobs?filter=latest&per_page=100" \
        --jq '.jobs[] | select(.conclusion == "success" and (.name | startswith("cycle_worker ("))) |
          .name | capture("(?<shard>[a-z-]+-[0-9]{4})").shard')"
    fi
    [[ -n "$shards" ]] || { echo '::error::The selected run has no completed financial Batch shards.'; exit 2; }
    while IFS= read -r shard; do
      [[ "$shard" =~ ^[a-z-]+-[0-9]{4}$ && -f "campaign-batch-state/$shard.sqlite" ]] || {
        echo '::error::A reserved Batch shard is absent from its cumulative checkpoint.'
        exit 2
      }
    done <<< "$shards"
    python -m src.research_cycle restore --plan cycle-working/plan --state cycle-working/state --input campaign-batch-state
    ;;
  continue|resume|promote)
    IFS=$'\t' read -r lease_name lease_run _ <<< "$latest_lease"
    [[ "$lease_run" == "$anchor" && "$lease_name" == "garp-cycle-$GARP_CYCLE-campaign-lease-$anchor" ]] || {
      echo '::error::Continuation must name the latest campaign lease. No provider work was reserved.'
      exit 2
    }
    gh run download "$anchor" --name "$lease_name" --dir campaign-parent
    names="$(gh api --paginate "$api/runs/$anchor/artifacts?per_page=100" \
      --jq '.artifacts[] | select(.expired == false) | .name')"
    if [[ $'\n'"$names"$'\n' == *$'\n'"garp-campaign-$GARP_CYCLE-$anchor"$'\n'* ]]; then
      gh run download "$anchor" --name "garp-campaign-$GARP_CYCLE-$anchor" --dir campaign-parent/report
    fi
    if [[ -f campaign-parent/report/74_campaign_manifest.json ]]; then
      cp campaign-parent/report/74_campaign_manifest.json campaign-parent/
    else
      [[ "$GARP_CAMPAIGN_MODE" == resume ]] && jq -e '.conclusion != "success"' <<< "$run" >/dev/null || {
        echo '::error::Campaign report is missing. Review the failed wave and resume explicitly.'
        exit 2
      }
      touch campaign-parent/recover
    fi
    if [[ $'\n'"$names"$'\n' == *$'\n'"garp-cycle-$GARP_CYCLE-state-1"$'\n'* ]]; then
      gh run download "$anchor" --name "garp-cycle-$GARP_CYCLE-state-1" --dir campaign-parent/state
      python -m src.research_cycle restore --plan cycle-working/plan --state cycle-working/state --input campaign-parent/state
    elif [[ -f campaign-parent/74_campaign_manifest.json ]]; then
      jq -e '.checkpoint_attempts_after == 0' campaign-parent/74_campaign_manifest.json >/dev/null
    fi
    ;;
  *) exit 2;;
esac
