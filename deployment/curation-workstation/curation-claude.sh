#!/bin/bash
# Runs Claude Code with Remote Control in the boot service's tmux session,
# starting it again whenever it exits. The loop runs inside tmux, rather than
# systemd restarting the service, so the session stays attachable throughout.
set -u

name="$1"
while true; do
  "$HOME/.local/bin/claude" --remote-control "$name"
  echo "Claude Code exited; starting it again in 10 seconds."
  sleep 10
done
