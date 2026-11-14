#!/bin/bash
# Puts the tracker upload key, an IAM user's access key limited to uploading to
# the tracker's bucket, in the curator's ~/.aws/credentials as the @PROFILE@
# profile, mode 600, as the curator. make curation-set-upload-key runs it as
# ssm-user in a Session Manager session. Both parts are read without echoing
# them, so the session log never shows them, and neither is a command-line
# argument. bootstrap.sh fills in @USER@, @HOME@ and @PROFILE@.
set -euo pipefail

credentials=@HOME@/.aws/credentials

read -rsp 'Access key ID: ' key_id
echo
read -rsp 'Secret access key: ' secret
echo
[[ $key_id =~ ^AKIA[A-Z0-9]{16}$ ]] || { echo "error: not an IAM user's access key ID (AKIA and 16 more characters)" >&2; exit 1; }
[[ -n $secret ]] || { echo "error: no secret access key entered" >&2; exit 1; }
sudo -u @USER@ install -m 600 /dev/null "$credentials"
printf '[%s]\naws_access_key_id = %s\naws_secret_access_key = %s\n' @PROFILE@ "$key_id" "$secret" |
  sudo -u @USER@ tee "$credentials" >/dev/null
echo "Written to $credentials as the @PROFILE@ profile. Ask for check_environment in the Claude session to confirm uploads are ready."
