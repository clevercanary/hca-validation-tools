#!/bin/bash
# Sets up the curation workstation, once, at the instance's first boot. The
# instance's user_data runs it as root, from a clone in /opt at a pinned commit,
# after writing /etc/curation-workstation.conf. It refuses a second run: a
# change reaches the machine by replacing the instance
# (docs/curation-workstation-contract.md 1.2). The curator's home is set up by
# setup-curator.sh, run as the curator.
set -euo pipefail

CONF=/etc/curation-workstation.conf
MARKER=/var/lib/curation-workstation/bootstrapped
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARIA2_VERSION=1.37.0
ARIA2_SHA256=60a420ad7085eb616cb6e2bdf0a7206d68ff3d37fb5a956dc44242eb2f79b66b
ARIA2_URL="https://github.com/aria2/aria2/releases/download/release-${ARIA2_VERSION}/aria2-${ARIA2_VERSION}.tar.xz"
UV_VERSION=0.10.9
UV_SHA256=20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594
UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
CURATION_USER=curator
HOME_DIR=/home/$CURATION_USER
DATA_MOUNT=/srv/curation-data
SCRATCH_DIR=$DATA_MOUNT/tmp
# Terraform attaches the data volume after the instance starts.
DEVICE_WAIT_SECONDS=300

step() { echo "== $*"; }
die() { echo "error: $*" >&2; exit 1; }

write_file() {
  local path=$1 mode=$2 content=$3 tmp
  tmp=$(mktemp)
  printf '%s\n' "$content" > "$tmp"
  install -o root -g root -m "$mode" "$tmp" "$path"
  rm "$tmp"
}

# A sudoers file sudo cannot parse would break sudo, so each is checked first.
write_sudoers() {
  local path=$1 content=$2 check
  check=$(mktemp)
  printf '%s\n' "$content" > "$check"
  visudo -cqf "$check" || die "visudo rejected $path"
  install -o root -g root -m 440 "$check" "$path"
  rm "$check"
}

verify_sha256() {
  local file=$1 expected=$2 actual
  actual=$(sha256sum "$file" | cut -d' ' -f1)
  [[ $actual == "$expected" ]] || die "checksum mismatch for $file: expected $expected, got $actual"
}

[[ $EUID -eq 0 ]] || die "run as root, from the instance's user_data"
[[ -e $MARKER ]] && die "this instance's first boot already ran ($(head -1 "$MARKER")); replace the instance instead of running this again"
mkdir -p "$(dirname "$MARKER")"
# Written at the start, so a failed first boot is not retried on the same instance either.
# It is also the first boot's record, which curation-status shows.
echo "first boot started $(date -u +%FT%TZ)" > "$MARKER"
record_failure() {
  local status=$?
  ((status == 0)) || echo "first boot failed $(date -u +%FT%TZ) (exit $status); see /var/log/cloud-init-output.log" >> "$MARKER"
}
trap record_failure EXIT
# Installed first, so it can report a first boot that fails.
install -m 755 "$SCRIPT_DIR/curation-status.sh" /usr/local/bin/curation-status

# Read as KEY=value lines, never sourced, so no value runs as a command; a key
# missing from the file stays empty and fails its check below.
CURATION_UID='' REPO_URL='' REPO_COMMIT='' DATA_DEVICE='' REMOTE_CONTROL_NAME=''
AWS_REGION='' ODP_PROFILE='' ODP_ROLE_ARN=''
[[ -f $CONF ]] || die "$CONF not found; the instance's user_data writes it"
while IFS='=' read -r key value; do
  case $key in
    '' | '#'*) ;;
    CURATION_UID | REPO_URL | REPO_COMMIT | DATA_DEVICE | REMOTE_CONTROL_NAME | AWS_REGION | ODP_PROFILE | ODP_ROLE_ARN)
      printf -v "$key" '%s' "$value" ;;
    *) die "unknown key $key in $CONF" ;;
  esac
done < "$CONF"
# Each is substituted into a unit, a script or a path.
[[ $CURATION_UID =~ ^[1-9][0-9]{3,4}$ ]] || die "CURATION_UID must be a number from 1000 to 99999"
[[ $REMOTE_CONTROL_NAME =~ ^[A-Za-z0-9._-]+$ ]] || die "REMOTE_CONTROL_NAME may hold only letters, digits, '.', '_' and '-'"
[[ $REPO_URL =~ ^https://[A-Za-z0-9./_-]+$ ]] || die "REPO_URL must be a plain https URL"
[[ $REPO_COMMIT =~ ^[0-9a-f]{40}$ ]] || die "REPO_COMMIT must be a full commit SHA"
# The EBS volume's serial is its ID, so this path can name no other disk.
[[ $DATA_DEVICE =~ ^/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol[0-9a-f]{8,17}$ ]] ||
  die "DATA_DEVICE must be the volume's /dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol... path"
[[ $AWS_REGION =~ ^[a-z]{2}(-[a-z]+)+-[0-9]+$ ]] || die "AWS_REGION must be a region name, such as us-east-1"
[[ $ODP_PROFILE =~ ^[A-Za-z0-9._-]+$ ]] || die "ODP_PROFILE may hold only letters, digits, '.', '_' and '-'"
[[ $ODP_ROLE_ARN =~ ^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$ ]] || die "ODP_ROLE_ARN must be an IAM role ARN"

step "the curator, with a fixed UID and a private home"
useradd --uid "$CURATION_UID" --create-home --shell /bin/bash "$CURATION_USER"
chmod 700 "$HOME_DIR"

# The image's default user has passwordless sudo from cloud-init; no one logs in as it.
step "removing ec2-user, which could become root"
if id ec2-user >/dev/null 2>&1; then userdel --remove ec2-user; fi
rm -f /etc/sudoers.d/90-cloud-init-users

# The SSM agent would create ssm-user at the first session with full sudo; it
# is created here first, and may become the curator only (contract 3.2.4).
step "ssm-user, which may become the curator but not root"
id ssm-user >/dev/null 2>&1 || useradd --create-home --shell /bin/bash ssm-user
write_sudoers /etc/sudoers.d/ssm-agent-users "ssm-user ALL=($CURATION_USER) NOPASSWD: ALL"
write_sudoers /etc/sudoers.d/curation-use-pty 'Defaults use_pty'

step "packages from the Amazon Linux repository, and aria2's build tools"
# Amazon Linux 2023 otherwise stays on the repository version the AMI shipped with.
write_file /etc/dnf/vars/releasever 644 latest
# Only the build tools the image lacks are installed, so removing them after takes nothing it shipped with.
build_deps=()
for pkg in gcc-c++ make pkgconf-pkg-config openssl-devel libxml2-devel zlib-devel; do
  rpm -q "$pkg" >/dev/null || build_deps+=("$pkg")
done
# python3.11 is CI's Python, from the repository, so uv uses it instead of downloading one.
dnf -y -q install tmux git dnf-automatic python3.11 "${build_deps[@]}"

step "aria2 $ARIA2_VERSION, built from a pinned source tarball"
build=$(mktemp -d)
curl -fsSL -o "$build/aria2.tar.xz" "$ARIA2_URL"
verify_sha256 "$build/aria2.tar.xz" "$ARIA2_SHA256"
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

# Started after the last dnf transaction above, so it cannot hold dnf's lock during them.
step "security updates, applied by dnf-automatic"
sed -i -e 's/^upgrade_type = .*/upgrade_type = security/' -e 's/^apply_updates = .*/apply_updates = yes/' \
  /etc/dnf/automatic.conf
systemctl enable --now dnf-automatic.timer

step "uv $UV_VERSION"
tmp=$(mktemp -d)
curl -fsSL -o "$tmp/uv.tar.gz" "$UV_URL"
verify_sha256 "$tmp/uv.tar.gz" "$UV_SHA256"
tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
install -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$tmp/uv-x86_64-unknown-linux-gnu/uvx" /usr/local/bin/
rm -rf "$tmp"

step "the data volume at $DATA_MOUNT"
for ((waited = 0; waited < DEVICE_WAIT_SECONDS; waited += 5)); do
  [[ -b $DATA_DEVICE ]] && break
  sleep 5
done
[[ -b $DATA_DEVICE ]] || die "$DATA_DEVICE did not appear within $DEVICE_WAIT_SECONDS seconds"
device=$(readlink -f "$DATA_DEVICE")
# A backstop: a disk with partitions, or anything mounted, as the root disk has, is refused.
[[ "$(lsblk -n -o NAME "$device" | wc -l)" == 1 ]] || die "$device has partitions; check DATA_DEVICE"
[[ -z "$(lsblk -n -o MOUNTPOINTS "$device" | tr -d '[:space:]')" ]] || die "$device is already mounted; check DATA_DEVICE"
fstype=$(blkid -s TYPE -o value "$device" || true)
formatted=no
if [[ -z $fstype ]]; then
  echo "formatting $device, which holds no filesystem"
  mkfs.xfs -q "$device"
  formatted=yes
elif [[ $fstype != xfs ]]; then
  die "$device holds a $fstype filesystem, not xfs; refusing to touch it"
fi
# The volume holds what the curator wrote, so no setuid file or device node on it is honoured.
printf 'UUID=%s %s xfs defaults,nofail,nosuid,nodev 0 2\n' "$(blkid -s UUID -o value "$device")" "$DATA_MOUNT" >> /etc/fstab
systemctl daemon-reload
mkdir -p "$DATA_MOUNT"
mount "$DATA_MOUNT"
# A new volume's top folder is given to the curator. A volume from an earlier
# instance already belongs to the curator's fixed UID; root does not walk it.
owner=$(stat -c '%u' "$DATA_MOUNT")
if [[ $formatted == yes ]]; then
  chown "$CURATION_USER:$CURATION_USER" "$DATA_MOUNT"
elif [[ $owner != "$CURATION_UID" ]]; then
  die "$DATA_MOUNT belongs to UID $owner, not CURATION_UID $CURATION_UID; set CURATION_UID to $owner"
fi
chmod 700 "$DATA_MOUNT"
# Scratch older than 10 days is removed, as in /tmp; the curator makes the folder.
write_file /etc/tmpfiles.d/curation-scratch.conf 644 "e $SCRATCH_DIR - - - 10d"

step "Claude Code's managed settings, which no user or project setting overrides"
install -d -m 755 /etc/claude-code
write_file /etc/claude-code/managed-settings.json 644 "{
  \"permissions\": {
    \"deny\": [\"Read(**/.env)\"]
  }
}"

step "the curator's home, set up as the curator"
sudo -u "$CURATION_USER" -H env REPO_URL="$REPO_URL" REPO_COMMIT="$REPO_COMMIT" AWS_REGION="$AWS_REGION" \
  ODP_PROFILE="$ODP_PROFILE" ODP_ROLE_ARN="$ODP_ROLE_ARN" DATA_MOUNT="$DATA_MOUNT" \
  bash "$SCRIPT_DIR/setup-curator.sh" </dev/null

step "the Remote Control boot service and the helper commands"
write_file /usr/local/bin/curation-attach 755 "$(sed -e "s|@USER@|$CURATION_USER|g" -e "s|@HOME@|$HOME_DIR|g" "$SCRIPT_DIR/curation-attach.sh")"
install -m 755 "$SCRIPT_DIR/curation-claude.sh" /usr/local/bin/curation-claude
write_file /etc/systemd/system/curation-remote-control.service 644 "$(sed -e "s|@USER@|$CURATION_USER|g" -e "s|@HOME@|$HOME_DIR|g" \
  -e "s|@DATA_MOUNT@|$DATA_MOUNT|g" -e "s|@SCRATCH@|$SCRATCH_DIR|g" -e "s|@NAME@|$REMOTE_CONTROL_NAME|g" \
  "$SCRIPT_DIR/curation-remote-control.service")"
systemctl daemon-reload
systemctl enable --now curation-remote-control

echo "first boot done $(date -u +%FT%TZ) at commit $REPO_COMMIT" | tee -a "$MARKER"
