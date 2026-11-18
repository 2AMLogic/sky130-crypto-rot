#!/bin/sh
# Event-aware changed-path gate shared by ci.yml's `verify` and
# `netlist-freshness` jobs (issue #283). Before this script the two jobs
# carried duplicate inline `changed` steps whose `git diff | grep -Eq` was
# fail-open: a failing `git diff` (empty base, missing ref) fed grep nothing,
# grep exited 1, and the job passed with every step skipped. This script
# keeps each event's behavior but fails closed, and is unit-tested by
# verification/test_ci_changed.py.
#
# Pattern adopted from sky130-comparator#332 (scripts/check-sim-append-only.py
# + .github/workflows/t1-signoff.yml), the fleet's merge-queue adaptation: a
# merge_group run diffs the trial-merge base/head from the event payload;
# every other event's behavior is unchanged. That gate checks append-only
# sim evidence -- a different contract -- so this is a pattern reuse, not an
# import (reuse.lock.json carries nothing for it; see 2am/REUSE.md,
# "One source for a gate").
#
# Usage: scripts/ci-changed.sh <ERE path regex>
# Environment (from the workflow step):
#   EVENT_NAME  github.event_name
#   BASE_REF    github.base_ref                     (pull_request)
#   BASE_SHA    github.event.merge_group.base_sha   (merge_group)
#   HEAD_SHA    github.event.merge_group.head_sha   (merge_group; default HEAD)
#
# stdout: exactly one line, `run=true` or `run=false`; diagnostics go to
# stderr. Exit 0 = decided. Exit 1 = FAIL CLOSED: the changed set could not
# be determined (empty or unresolvable base, failing git diff, broken
# filter), and the job must fail rather than skip its steps.
#
# The checkout must supply history (actions/checkout fetch-depth: 0).

set -u

if [ "${1:-}" = "" ]; then
  echo "ci-changed: usage: ci-changed.sh <path-regex>" >&2
  exit 1
fi
regex=$1
EVENT_NAME=${EVENT_NAME:-}
BASE_REF=${BASE_REF:-}
BASE_SHA=${BASE_SHA:-}
HEAD_SHA=${HEAD_SHA:-}

die() {
  echo "ci-changed: FAIL-CLOSED: $*" >&2
  exit 1
}

case $EVENT_NAME in
  pull_request)
    # The same diff the inline steps ran. A pull_request event always
    # carries base_ref; an empty one means the payload was not what the
    # workflow assumed -- refuse instead of diffing nothing.
    [ -n "$BASE_REF" ] ||
      die "pull_request has an empty BASE_REF (github.base_ref absent?)"
    range="origin/${BASE_REF}...HEAD"
    ;;
  merge_group)
    # The merge queue's trial merge: base and head come from the event
    # payload, not a branch ref -- github.base_ref is empty on merge_group.
    # An absent HEAD_SHA falls back to the checked-out merge commit.
    [ -n "$BASE_SHA" ] ||
      die "merge_group has an empty BASE_SHA (github.event.merge_group.base_sha absent?)"
    range="${BASE_SHA}...${HEAD_SHA:-HEAD}"
    ;;
  *)
    # push, workflow_dispatch, and anything else: run every step, as before.
    echo "run=true"
    exit 0
    ;;
esac

# git's status is captured explicitly: `if git diff | grep -q` would swallow
# a failing git diff -- grep sees empty input and reports "no match" -- the
# fail-open this script exists to close.
if ! paths=$(git diff --name-only "$range" 2>&1); then
  die "git diff --name-only '$range' failed: $paths"
fi

# grep: 0 = a watched path changed (run), 1 = none did (skip), >1 = a broken
# filter, which must not read as "skip".
status=0
printf '%s\n' "$paths" | grep -Eq -- "$regex" || status=$?
case $status in
  0)
    echo "run=true"
    ;;
  1)
    echo "run=false"
    echo "ci-changed: no changed path matches the job's filter; heavy steps skipped" >&2
    ;;
  *)
    die "grep failed on the job's path filter (broken regex '$regex'?)"
    ;;
esac
