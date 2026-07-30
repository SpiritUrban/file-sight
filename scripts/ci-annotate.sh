#!/usr/bin/env bash
# Print the tail of a log file as a GitHub annotation.
#
# Run logs are not readable without authentication even in a public
# repository ("Sign in to view logs"), while annotations are served by the
# API to anyone. So whatever a failing step knows must be pushed into an
# annotation at the moment it fails.
#
# IMPORTANT (rule 21a): GitHub truncates an annotation message at 4096
# characters and drops the TAIL -- which is exactly the line with the error.
# A `tail -c 6000` template therefore lies: it shows a plausible chunk of
# log with the cause cut off. Hence three non-negotiable measures below:
# a ~2500 char budget, ANSI stripping, and dropping known progress noise.
#
#   bash scripts/ci-annotate.sh "Build output" build.log [limit]

set -uo pipefail

title="${1:?annotation title required}"
file="${2:?log file required}"
limit="${3:-2500}"

if [ ! -s "$file" ]; then
  echo "::error title=${title}::${file} is missing or empty"
  exit 0
fi

# Strip ANSI escapes: cargo's colours eat half the budget on invisible bytes.
clean=$(sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' "$file")

# Progress chatter is never the cause of a failure, and there are hundreds of
# lines of it -- it is what pushes the real error past the 4096 limit. This is
# not rule-21 filtering (selecting by an expected error format); it is
# dropping a fixed list of known noise.
trimmed=$(printf '%s\n' "$clean" | grep -vE \
  '^[[:space:]]*(Compiling|Checking|Downloaded|Downloading|Fresh|Updating|Adding|Locking|Installing|Blocking|Collecting|Requirement already satisfied|added [0-9]+ package)' \
  || true)
# If the filter left nothing, show the log as it is -- a silent step is worse
# than a noisy one.
[ -n "$trimmed" ] && clean="$trimmed"

log=$(printf '%s' "$clean" | tail -c "$limit")

# GitHub's workflow-command escaping: these three must be encoded or the
# message is cut at the first newline.
log="${log//'%'/'%25'}"
log="${log//$'\r'/'%0D'}"
log="${log//$'\n'/'%0A'}"

echo "::error title=${title}::${log}"
