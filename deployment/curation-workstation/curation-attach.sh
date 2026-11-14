#!/bin/bash
# Attaches to the boot service's Claude Code session as the working user.
# Run from a Session Manager shell; detach with Ctrl-b d. bootstrap.sh fills
# in @USER@ and @HOME@.
exec sudo -iu @USER@ tmux -S @HOME@/.tmux-claude attach -t claude
