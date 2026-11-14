#!/bin/bash
# Sets up the curator's home. bootstrap.sh runs it as the curator, so every
# write here has only the curator's permissions (docs/curation-workstation-contract.md
# 2.1.1). Settings come from the environment bootstrap.sh passes.
set -euo pipefail

: "${REPO_URL:?}" "${REPO_REF:?}" "${AWS_REGION:?}" "${ODP_PROFILE:?}" "${ODP_ROLE_ARN:?}"
: "${DATA_MOUNT:?}" "${PYTHON_VERSION:?}" "${CLAUDE_INSTALLER_URL:?}"

DATA_LINK="$HOME/hca-tracker-upload"
CACHE_DIR="$DATA_LINK/.hca-tracker-cache"
REPO_DIR="$HOME/hca-validation-tools"

changed() { echo "changed: $*"; }
ok() { echo "ok: $*"; }

# Replaces a file only when its content or mode differ.
put_file() {
  local path=$1 mode=$2 content=$3
  if [[ -f $path ]] && [[ "$(cat "$path")" == "$content" ]] && [[ "$(stat -c '%a' "$path")" == "$mode" ]]; then
    ok "$path"
    return
  fi
  install -m "$mode" /dev/null "$path"
  printf '%s\n' "$content" > "$path"
  changed "$path"
}

put_dir() {
  local path=$1
  if [[ -d $path ]] && [[ "$(stat -c '%a' "$path")" == 700 ]]; then
    return
  fi
  install -d -m 700 "$path"
  changed "$path"
}

# --- Claude Code; the installer checks the binary against its release manifest ---
if [[ -x $HOME/.local/bin/claude ]]; then
  ok "Claude Code ($("$HOME/.local/bin/claude" --version))"
else
  installer=$(mktemp)
  curl -fsSL -o "$installer" "$CLAUDE_INSTALLER_URL"
  bash "$installer"
  rm "$installer"
  changed "Claude Code"
fi
# shellcheck disable=SC2016 # written literally, for .bashrc to expand
path_line='export PATH="$HOME/.local/bin:$PATH"'
if grep -qxF "$path_line" "$HOME/.bashrc"; then
  ok "PATH in .bashrc"
else
  printf '%s\n' "$path_line" >> "$HOME/.bashrc"
  changed "PATH in .bashrc"
fi

# --- ~/hca-tracker-upload, a link to the data volume ---
if [[ -L $DATA_LINK ]] && [[ "$(readlink "$DATA_LINK")" == "$DATA_MOUNT" ]]; then
  ok "$DATA_LINK"
else
  # An empty folder is left where the volume used to be mounted.
  if [[ -d $DATA_LINK && ! -L $DATA_LINK ]]; then rmdir "$DATA_LINK"; fi
  ln -sfn "$DATA_MOUNT" "$DATA_LINK"
  changed "$DATA_LINK"
fi
# Downloads land under the tracker client's cache folder, which defaults to the root volume.
put_dir "$CACHE_DIR"

# --- This repo, with the MCP servers' environments ---
if [[ -d $REPO_DIR/.git ]]; then
  ok "$REPO_DIR ($(git -C "$REPO_DIR" rev-parse --short HEAD))"
else
  git clone --quiet --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR"
  changed "$REPO_DIR"
fi
for pkg in hca-anndata-mcp hca-tracker-mcp; do
  /usr/local/bin/uv sync --quiet --no-dev --python "$PYTHON_VERSION" --directory "$REPO_DIR/packages/$pkg"
  echo "synced: $pkg"
done

# --- Configuration ---
put_dir "$HOME/.claude"
put_dir "$HOME/.aws"
put_file "$REPO_DIR/.mcp.json" 600 "{
  \"mcpServers\": {
    \"hca-anndata-mcp\": {
      \"command\": \"$REPO_DIR/packages/hca-anndata-mcp/.venv/bin/hca-anndata-mcp\",
      \"args\": []
    },
    \"hca-tracker\": {
      \"command\": \"$REPO_DIR/packages/hca-tracker-mcp/.venv/bin/hca-tracker-mcp\",
      \"args\": [],
      \"env\": {\"HCA_TRACKER_CACHE_DIR\": \"$CACHE_DIR\"}
    }
  }
}"
put_file "$HOME/.aws/config" 600 "[default]
region = $AWS_REGION
sts_regional_endpoints = regional

[profile $ODP_PROFILE]
role_arn = $ODP_ROLE_ARN
credential_source = Ec2InstanceMetadata
region = $AWS_REGION
sts_regional_endpoints = regional"
env_file=$REPO_DIR/.env
if [[ ! -f $env_file ]]; then
  echo "todo: put the tracker token in $env_file (see README)"
elif [[ "$(stat -c '%a' "$env_file")" == 600 ]]; then
  ok "$env_file"
else
  chmod 600 "$env_file"
  changed "$env_file"
fi
