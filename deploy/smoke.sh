#!/usr/bin/env sh
set -eu

: "${DEMO_URL:?Set DEMO_URL, for example https://demo.example.com}"
: "${DEMO_BASIC_AUTH_USER:?Set DEMO_BASIC_AUTH_USER}"
: "${DEMO_BASIC_AUTH_PASSWORD:?Set DEMO_BASIC_AUTH_PASSWORD}"

AUTH="${DEMO_BASIC_AUTH_USER}:${DEMO_BASIC_AUTH_PASSWORD}"

curl --fail --silent --show-error --user "$AUTH" \
  "$DEMO_URL/api/v1/health" >/dev/null
curl --fail --silent --show-error --user "$AUTH" \
  "$DEMO_URL/" >/dev/null

echo "Demo HTTP smoke checks passed"

