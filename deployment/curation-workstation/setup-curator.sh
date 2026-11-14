#!/bin/bash
# Sets up the curator's home at first boot. bootstrap.sh runs it as the curator,
# so every write here has only the curator's permissions
# (docs/curation-workstation-contract.md 3.1.2). Settings come from the
# environment bootstrap.sh passes.
set -euo pipefail

CLAUDE_INSTALLER_URL=https://claude.ai/install.sh
# CI's Python, installed by bootstrap.sh from the repository: left to itself, uv
# picks the newest, for which some dependencies publish no wheels.
PYTHON_VERSION=3.11
export UV_PYTHON_DOWNLOADS=never

DATA_LINK="$HOME/hca-tracker-upload"
CACHE_DIR="$DATA_LINK/.hca-tracker-cache"
LOGS_DIR="$DATA_LINK/.claude-projects"
REPO_DIR="$HOME/hca-validation-tools"

step() { echo "== $*"; }
umask 077

# Before the installer runs, so ~/.claude/projects is the link and not a folder the installer made.
step "the data volume, as ~/hca-tracker-upload, with the download cache, scratch and Claude's logs"
ln -sT "$DATA_MOUNT" "$DATA_LINK"
# The volume outlives the instance, so these may already be there.
mkdir -p "$CACHE_DIR" "$DATA_LINK/tmp" "$LOGS_DIR"
mkdir "$HOME/.claude"
ln -sT "$LOGS_DIR" "$HOME/.claude/projects"

step "Claude Code; the installer checks the binary against its release manifest"
installer=$(mktemp)
curl -fsSL -o "$installer" "$CLAUDE_INSTALLER_URL"
bash "$installer"
rm "$installer"
# shellcheck disable=SC2016 # written literally, for .bashrc to expand
printf '%s\n' 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

step "this repo at $REPO_COMMIT, with the MCP servers' environments"
git clone --quiet "$REPO_URL" "$REPO_DIR"
git -C "$REPO_DIR" checkout --quiet "$REPO_COMMIT"
for pkg in hca-anndata-mcp hca-tracker-mcp; do
  /usr/local/bin/uv sync --quiet --no-dev --python "$PYTHON_VERSION" --directory "$REPO_DIR/packages/$pkg"
done

step "the MCP servers and AWS configuration"
cat > "$REPO_DIR/.mcp.json" <<EOF
{
  "mcpServers": {
    "hca-anndata-mcp": {
      "command": "$REPO_DIR/packages/hca-anndata-mcp/.venv/bin/hca-anndata-mcp",
      "args": []
    },
    "hca-tracker": {
      "command": "$REPO_DIR/packages/hca-tracker-mcp/.venv/bin/hca-tracker-mcp",
      "args": [],
      "env": {"HCA_TRACKER_CACHE_DIR": "$CACHE_DIR"}
    }
  }
}
EOF
mkdir "$HOME/.aws"
cat > "$HOME/.aws/config" <<EOF
[default]
region = $AWS_REGION
sts_regional_endpoints = regional

[profile $ODP_PROFILE]
role_arn = $ODP_ROLE_ARN
credential_source = Ec2InstanceMetadata
region = $AWS_REGION
sts_regional_endpoints = regional
EOF

echo "todo: put the tracker token in $REPO_DIR/.env (see README)"
