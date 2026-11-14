#!/bin/bash
# Sets up the curation workstation. This is root's part: the curator, the
# software, the data volume, Claude Code's managed settings and the Remote
# Control boot service. It touches only system paths; the curator's home is set
# up by setup-curator.sh, run as the curator (docs/curation-workstation-contract.md).
# Run as root (sudo) from a Session Manager shell. Each step checks first, so a
# second run changes nothing. Reads /etc/curation-workstation.conf.
set -euo pipefail

CONF=/etc/curation-workstation.conf
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARIA2_VERSION=1.37.0
ARIA2_SHA256=60a420ad7085eb616cb6e2bdf0a7206d68ff3d37fb5a956dc44242eb2f79b66b
ARIA2_URL="https://github.com/aria2/aria2/releases/download/release-${ARIA2_VERSION}/aria2-${ARIA2_VERSION}.tar.xz"
UV_VERSION=0.10.9
UV_SHA256=20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594
UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
CLAUDE_INSTALLER_URL=https://claude.ai/install.sh
# CI's Python: left to itself, uv picks the newest, for which some pinned
# dependencies publish no wheels.
PYTHON_VERSION=3.11
# Outside the curator's home, so root mounts it under a root-owned parent; the
# curator's ~/hca-tracker-upload is a link to it.
DATA_MOUNT=/srv/curation-data

changes=0
changed() { echo "changed: $*"; changes=$((changes + 1)); }
ok() { echo "ok: $*"; }
die() { echo "error: $*" >&2; exit 1; }

# Root never writes inside the curator's home; setup-curator.sh does, as the curator.
refuse_curator_home() {
  case $1 in "$HOME_DIR"/*) die "refusing to write $1 as root: it is in the curator's home" ;; esac
}

# Replaces a file only when its content, owner or mode differ.
put_file() {
  local path=$1 owner=$2 mode=$3 content=$4
  refuse_curator_home "$path"
  if [[ -f $path ]] && [[ "$(cat "$path")" == "$content" ]] \
    && [[ "$(stat -c '%U %a' "$path")" == "$owner $mode" ]]; then
    ok "$path"
    return
  fi
  install -o "$owner" -g "$owner" -m "$mode" /dev/null "$path"
  printf '%s\n' "$content" > "$path"
  changed "$path"
}

put_dir() {
  local path=$1 owner=$2 mode=$3
  refuse_curator_home "$path"
  if [[ -d $path ]] && [[ "$(stat -c '%U %a' "$path")" == "$owner $mode" ]]; then
    return
  fi
  install -d -o "$owner" -g "$owner" -m "$mode" "$path"
  changed "$path"
}

verify_sha256() {
  local file=$1 expected=$2 actual
  actual=$(sha256sum "$file" | cut -d' ' -f1)
  [[ $actual == "$expected" ]] || die "checksum mismatch for $file: expected $expected, got $actual"
}

[[ $EUID -eq 0 ]] || die "run as root: sudo $0"
# Root runs these scripts and installs some of them, so no one else may be able
# to change them or any folder above them (contract 2.1.3).
root_only() { [[ "$(stat -c '%u' "$1")" == 0 && -z "$(find "$1" -maxdepth 0 -perm /022)" ]]; }
dir=$SCRIPT_DIR
while [[ $dir != / ]]; do
  root_only "$dir" || die "$dir is not root's alone; clone this repo where only root can write, e.g. /opt (see README)"
  dir=$(dirname "$dir")
done
for f in "$SCRIPT_DIR"/*; do
  root_only "$f" || die "$f is not root's alone"
done
[[ -f $CONF ]] || die "$CONF not found; copy curation-workstation.conf.example there and fill it in"
# shellcheck source=curation-workstation.conf.example
. "$CONF"
for key in CURATION_USER REPO_URL REPO_REF DATA_DEVICE REMOTE_CONTROL_NAME AWS_REGION ODP_PROFILE ODP_ROLE_ARN; do
  [[ -n ${!key:-} ]] || die "$key is not set in $CONF"
done
# Both are substituted into the systemd unit and helper scripts.
[[ $CURATION_USER =~ ^[a-z_][a-z0-9_-]*$ ]] || die "CURATION_USER must be a plain user name"
[[ $REMOTE_CONTROL_NAME =~ ^[A-Za-z0-9._-]+$ ]] || die "REMOTE_CONTROL_NAME may hold only letters, digits, '.', '_' and '-'"
# These end up in the curator's config files and commands.
[[ $REPO_URL =~ ^https://[A-Za-z0-9./_-]+$ ]] || die "REPO_URL must be a plain https URL"
[[ $REPO_REF =~ ^[A-Za-z0-9._/-]+$ ]] || die "REPO_REF must be a branch or tag name"
[[ $DATA_DEVICE =~ ^/dev/[A-Za-z0-9/_-]+$ ]] || die "DATA_DEVICE must be a /dev path"
[[ $AWS_REGION =~ ^[a-z]{2}(-[a-z]+)+-[0-9]+$ ]] || die "AWS_REGION must be a region name, such as us-east-1"
[[ $ODP_PROFILE =~ ^[A-Za-z0-9._-]+$ ]] || die "ODP_PROFILE may hold only letters, digits, '.', '_' and '-'"
[[ $ODP_ROLE_ARN =~ ^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$ ]] || die "ODP_ROLE_ARN must be an IAM role ARN"
HOME_DIR="/home/$CURATION_USER"

# --- The curator, without sudo ---
if id "$CURATION_USER" >/dev/null 2>&1; then
  ok "user $CURATION_USER"
else
  useradd --create-home --shell /bin/bash "$CURATION_USER"
  changed "user $CURATION_USER"
fi
sudo_rights=$(LC_ALL=C sudo -l -U "$CURATION_USER" 2>&1 || true)
[[ $sudo_rights == *"is not allowed to run sudo"* ]] || die "$CURATION_USER has sudo rights; remove them"
# The home folder itself is the one path root sets in it; its parent, /home, is root's.
[[ -L $HOME_DIR ]] && die "$HOME_DIR is a symlink"
if [[ "$(stat -c '%U %a' "$HOME_DIR")" == "$CURATION_USER 700" ]]; then
  ok "$HOME_DIR"
else
  chown -h "$CURATION_USER:$CURATION_USER" "$HOME_DIR"
  chmod 700 "$HOME_DIR"
  changed "$HOME_DIR"
fi

# --- Packages from the Amazon Linux repository, with security updates ---
for pkg in tmux git dnf-automatic; do
  if rpm -q "$pkg" >/dev/null; then ok "$pkg"; else dnf -y -q install "$pkg"; changed "$pkg"; fi
done
# Amazon Linux 2023 otherwise stays on the repository version the AMI shipped with.
put_file /etc/dnf/vars/releasever root 644 latest
automatic=/etc/dnf/automatic.conf
if grep -qx 'upgrade_type = security' "$automatic" && grep -qx 'apply_updates = yes' "$automatic"; then
  ok "$automatic"
else
  sed -i -e 's/^upgrade_type = .*/upgrade_type = security/' -e 's/^apply_updates = .*/apply_updates = yes/' "$automatic"
  changed "$automatic"
fi
if systemctl is-enabled --quiet dnf-automatic.timer && systemctl is-active --quiet dnf-automatic.timer; then
  ok dnf-automatic.timer
else
  systemctl enable --now dnf-automatic.timer
  changed dnf-automatic.timer
fi

# --- aria2, built from a pinned source tarball; the build tools are removed after ---
aria2_version=$(/usr/local/bin/aria2c --version 2>/dev/null | head -1 || true)
if [[ $aria2_version == "aria2 version $ARIA2_VERSION" ]]; then
  ok "aria2 $ARIA2_VERSION"
else
  build=$(mktemp -d)
  curl -fsSL -o "$build/aria2.tar.xz" "$ARIA2_URL"
  verify_sha256 "$build/aria2.tar.xz" "$ARIA2_SHA256"
  build_deps=()
  for pkg in gcc-c++ make pkgconf-pkg-config openssl-devel libxml2-devel zlib-devel; do
    rpm -q "$pkg" >/dev/null || build_deps+=("$pkg")
  done
  ((${#build_deps[@]} == 0)) || dnf -y -q install "${build_deps[@]}"
  tar -xJf "$build/aria2.tar.xz" -C "$build"
  (
    cd "$build/aria2-$ARIA2_VERSION"
    ./configure --quiet --with-openssl --without-gnutls --with-libxml2 --without-libexpat \
      --without-sqlite3 --without-libssh2 --without-libcares --without-libuv --disable-nls
    make -s -j"$(nproc)"
  )
  install -m 755 "$build/aria2-$ARIA2_VERSION/src/aria2c" /usr/local/bin/aria2c
  ((${#build_deps[@]} == 0)) || dnf -y -q remove "${build_deps[@]}"
  rm -rf "$build"
  changed "aria2 $ARIA2_VERSION"
fi

# --- uv, from a pinned release ---
if [[ "$(/usr/local/bin/uv --version 2>/dev/null)" == "uv $UV_VERSION"* ]]; then
  ok "uv $UV_VERSION"
else
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/uv.tar.gz" "$UV_URL"
  verify_sha256 "$tmp/uv.tar.gz" "$UV_SHA256"
  tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
  install -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$tmp/uv-x86_64-unknown-linux-gnu/uvx" /usr/local/bin/
  rm -rf "$tmp"
  changed "uv $UV_VERSION"
fi

# --- Data volume at /srv/curation-data, its top folder given to the curator ---
device=$(readlink -f "$DATA_DEVICE")
[[ -b $device ]] || die "$DATA_DEVICE is not a block device"
# A wrong device name could point at the root volume; chown -R below would hand it to the curator.
while read -r target; do
  [[ $target == "$DATA_MOUNT" ]] || die "$device is already mounted at $target; check DATA_DEVICE"
done < <(findmnt -n -o TARGET -S "$device" || true)
fstype=$(blkid -s TYPE -o value "$device" || true)
if [[ -z $fstype ]]; then
  mkfs.xfs -q "$device"
  changed "formatted $device"
elif [[ $fstype != xfs ]]; then
  die "$device holds a $fstype filesystem, not xfs; refusing to touch it"
fi
uuid=$(blkid -s UUID -o value "$device")
fstab_line="UUID=$uuid $DATA_MOUNT xfs defaults,nofail 0 2"
if grep -qxF "$fstab_line" /etc/fstab; then
  ok "/etc/fstab"
else
  # Any other entry for this volume, or for this folder (a replaced volume), is dropped.
  awk -v u="UUID=$uuid" -v d="$DATA_MOUNT" '!($1 == u || $2 == d)' /etc/fstab > /etc/fstab.new
  mv /etc/fstab.new /etc/fstab
  printf '%s\n' "$fstab_line" >> /etc/fstab
  systemctl daemon-reload
  changed "/etc/fstab"
fi
mkdir -p "$DATA_MOUNT"
if mountpoint -q "$DATA_MOUNT"; then ok "$DATA_MOUNT mounted"; else mount "$DATA_MOUNT"; changed "$DATA_MOUNT mounted"; fi
if [[ "$(stat -c '%U %a' "$DATA_MOUNT")" != "$CURATION_USER 700" ]]; then
  # -R without -L changes links, never what they point to.
  chown -R "$CURATION_USER:$CURATION_USER" "$DATA_MOUNT"
  chmod 700 "$DATA_MOUNT"
  changed "$DATA_MOUNT owner"
fi

# --- Claude Code's managed settings, which no user or project setting overrides ---
put_dir /etc/claude-code root 755
put_file /etc/claude-code/managed-settings.json root 644 '{
  "permissions": {
    "deny": ["Read(**/.env)"]
  }
}'

# --- sudo gives each command its own terminal, so a curator process cannot type into the operator's ---
# Checked before it is installed: a sudoers file sudo cannot parse would lock ssm-user out of sudo.
sudoers_use_pty='Defaults use_pty'
sudoers_check=$(mktemp)
printf '%s\n' "$sudoers_use_pty" > "$sudoers_check"
visudo -cqf "$sudoers_check" || die "visudo rejected the use_pty setting"
rm "$sudoers_check"
put_file /etc/sudoers.d/curation-use-pty root 440 "$sudoers_use_pty"

# --- The curator's home, set up as the curator ---
# Its output is relayed line by line, counting its changes; its last line is its exit status.
curator_status=none
while IFS= read -r line; do
  case $line in "exit: "*) curator_status=${line#exit: }; continue ;; esac
  echo "$line"
  if [[ $line == changed:* ]]; then changes=$((changes + 1)); fi
done < <(sudo -u "$CURATION_USER" -H env REPO_URL="$REPO_URL" REPO_REF="$REPO_REF" AWS_REGION="$AWS_REGION" \
  ODP_PROFILE="$ODP_PROFILE" ODP_ROLE_ARN="$ODP_ROLE_ARN" DATA_MOUNT="$DATA_MOUNT" \
  PYTHON_VERSION="$PYTHON_VERSION" CLAUDE_INSTALLER_URL="$CLAUDE_INSTALLER_URL" \
  bash "$SCRIPT_DIR/setup-curator.sh" 2>&1 && echo "exit: 0" || echo "exit: $?")
[[ $curator_status == 0 ]] || die "setup-curator.sh failed (exit status $curator_status)"

# --- Remote Control boot service and the helper commands ---
put_file /usr/local/bin/curation-attach root 755 "$(sed -e "s|@USER@|$CURATION_USER|g" -e "s|@HOME@|$HOME_DIR|g" "$SCRIPT_DIR/curation-attach.sh")"
changes_before_service=$changes
put_file /usr/local/bin/curation-claude root 755 "$(cat "$SCRIPT_DIR/curation-claude.sh")"
unit=/etc/systemd/system/curation-remote-control.service
put_file "$unit" root 644 "$(sed -e "s|@USER@|$CURATION_USER|g" -e "s|@HOME@|$HOME_DIR|g" \
  -e "s|@REPO_DIR@|$HOME_DIR/hca-validation-tools|g" -e "s|@DATA_MOUNT@|$DATA_MOUNT|g" -e "s|@NAME@|$REMOTE_CONTROL_NAME|g" \
  "$SCRIPT_DIR/curation-remote-control.service")"
systemctl daemon-reload
if systemctl is-enabled --quiet curation-remote-control && systemctl is-active --quiet curation-remote-control; then
  # A running service keeps the old unit and script, so a change waits for the next boot unless restarted.
  if ((changes > changes_before_service)); then
    systemctl restart curation-remote-control
    changed "curation-remote-control (restarted)"
  else
    ok curation-remote-control
  fi
else
  systemctl enable --now --quiet curation-remote-control
  changed curation-remote-control
fi

echo "done: $changes change(s)"
