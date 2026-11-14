#!/bin/bash
# Reports the first boot's progress and the data volume's use. make curation-status
# runs it in a Session Manager session, as ssm-user.
set -u

marker=/var/lib/curation-workstation/bootstrapped
if [[ -f $marker ]]; then cat "$marker"; else echo "first boot: not started"; fi
if mountpoint -q /srv/curation-data; then
  df -h --output=size,used,avail,pcent,target /srv/curation-data
else
  echo "data volume: not mounted at /srv/curation-data"
fi
