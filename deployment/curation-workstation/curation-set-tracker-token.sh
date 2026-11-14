#!/bin/bash
# Puts the tracker API token in the curator's .env, mode 600, as the curator.
# make curation-set-tracker-token runs it as ssm-user in a Session Manager
# session. The token is read without echoing it, so the session log never shows
# it, and it is never a command-line argument. bootstrap.sh fills in @HOME@.
set -euo pipefail

TRACKER_URL=https://tracker.data.humancellatlas.org
env_file=@HOME@/hca-validation-tools/.env

read -rsp 'Tracker API token: ' token
echo
[[ -n $token ]] || { echo "error: no token entered" >&2; exit 1; }
sudo -u curator install -m 600 /dev/null "$env_file"
printf 'HCA_TRACKER_URL=%s\nHCA_TRACKER_API_TOKEN=%s\n' "$TRACKER_URL" "$token" | sudo -u curator tee "$env_file" >/dev/null
echo "Written to $env_file. Run /mcp in the Claude session to reconnect the tracker server."
