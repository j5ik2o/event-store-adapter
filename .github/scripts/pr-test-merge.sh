#!/usr/bin/env bash
# Check out the test merge of the current base tip and the current head of a pull request.
#
# The event payload can carry an old base, and GitHub can keep refs/pull/N/merge on an old
# base for a long time, so both are checked against the pull request as it is now. When the
# candidate from GitHub stays old, the test merge is built here instead. A conflict fails.
#
# Inputs: PR_NUMBER, EVENT_HEAD_SHA, GITHUB_REPOSITORY, GH_TOKEN (for gh api).
# Optional: MERGE_REFETCHES (default 4), MERGE_RETRY_SECONDS (default 5).
set -euo pipefail

fail() {
  echo "::error::$*" >&2
  exit 1
}

parents_of() {
  # Read the raw headers because a shallow checkout hides parents from git log.
  git cat-file commit "$1" | awk 'BEGIN { header = 1 } /^$/ { header = 0 } header && $1 == "parent" { print $2 }'
}

[[ "${PR_NUMBER:-}" =~ ^[0-9]+$ ]] || fail "Invalid pull request number '${PR_NUMBER:-}'"
[[ "${EVENT_HEAD_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || fail "Invalid event head '${EVENT_HEAD_SHA:-}'"

current=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER" --jq '[.state, .base.ref, .head.sha] | @tsv')
IFS=$'\t' read -r state base_ref head_sha <<<"$current"
[[ "$state" == open ]] || fail "Pull request #$PR_NUMBER is $state"
[[ "$head_sha" =~ ^[0-9a-f]{40}$ && -n "$base_ref" ]] || fail "Cannot read the current base and head of #$PR_NUMBER"
if [[ "$head_sha" != "$EVENT_HEAD_SHA" ]]; then
  fail "Event head $EVENT_HEAD_SHA is not the current head $head_sha; the run for the current head decides"
fi

git fetch --no-tags --depth=1 origin "+refs/heads/$base_ref:refs/remotes/origin/$base_ref"
base_sha=$(git rev-parse "refs/remotes/origin/$base_ref^{commit}")
expected="$base_sha"$'\n'"$head_sha"
echo "Current base $base_ref@$base_sha, head $head_sha"

commit=$(git rev-parse HEAD)
refetches=${MERGE_REFETCHES:-4}
for ((refetch = 0; ; refetch++)); do
  if [[ -n "$commit" && "$(parents_of "$commit")" == "$expected" ]]; then
    git checkout --quiet --detach "$commit"
    echo "Verified GitHub test merge $commit with parents $base_sha $head_sha"
    exit 0
  fi
  echo "Candidate ${commit:-unavailable} does not have parents $base_sha $head_sha (re-fetch $refetch/$refetches)"
  ((refetch < refetches)) || break
  sleep "${MERGE_RETRY_SECONDS:-5}"
  # The base can move while waiting, so compare each candidate with the base tip fetched with it.
  commit=
  if git fetch --no-tags --depth=1 origin "+refs/heads/$base_ref:refs/remotes/origin/$base_ref" \
    "+refs/pull/$PR_NUMBER/merge:refs/remotes/pull/merge"; then
    base_sha=$(git rev-parse "refs/remotes/origin/$base_ref^{commit}")
    expected="$base_sha"$'\n'"$head_sha"
    commit=$(git rev-parse refs/remotes/pull/merge)
  fi
done

unshallow=()
[[ "$(git rev-parse --is-shallow-repository)" == true ]] && unshallow=(--unshallow)
git fetch --no-tags "${unshallow[@]}" origin \
  "+refs/heads/$base_ref:refs/remotes/origin/$base_ref" "+refs/pull/$PR_NUMBER/head:refs/remotes/pull/head"
fetched_head=$(git rev-parse refs/remotes/pull/head)
[[ "$fetched_head" == "$head_sha" ]] || fail "Fetched head $fetched_head is not $head_sha; the run for the current head decides"
# The base can also move after the last candidate, so build on the tip fetched now.
base_sha=$(git rev-parse "refs/remotes/origin/$base_ref^{commit}")
expected="$base_sha"$'\n'"$head_sha"
echo "GitHub test merge stays old; building the test merge of $base_ref@$base_sha and $head_sha"
tree=$(git merge-tree --write-tree "$base_sha" "$head_sha") || fail "$head_sha conflicts with $base_ref@$base_sha"
commit=$(GIT_AUTHOR_NAME=pr-ci GIT_AUTHOR_EMAIL=pr-ci@invalid GIT_AUTHOR_DATE='@0 +0000' \
  GIT_COMMITTER_NAME=pr-ci GIT_COMMITTER_EMAIL=pr-ci@invalid GIT_COMMITTER_DATE='@0 +0000' \
  git commit-tree "$tree" -p "$base_sha" -p "$head_sha" -m "Test merge of $head_sha into $base_sha")
[[ "$(parents_of "$commit")" == "$expected" ]] || fail "Built test merge $commit has unexpected parents"
git checkout --quiet --detach "$commit"
echo "Verified built test merge $commit with parents $base_sha $head_sha"
