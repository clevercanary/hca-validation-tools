# Curation Workstation Contract

## Keeping the workstation secure: who runs what, and who may write where

**Status:** Draft — assertions under discussion
**Date:** 2026-11-13
**Prompted by:** the review of #875 stage A, where two independent reviews found `bootstrap.sh` writing,
as `root`, into the curator's home

`root` sets up the machine. The curator owns its home. `root` never writes inside it.

## Overview

**What it is.** A prod EC2 instance for atlas curation, built by the `curation-workstation` module in
`hca-atlas-tracker-tf-config` and set up by `deployment/curation-workstation/` in this repo.

**What it is for.** Running the atlas work done on a laptop today, `/evaluate-h5ad`, `/curate-h5ad` and
the tracker and AnnData MCP servers, on a large machine with a large disk, driven by Claude Code from a
terminal on the operator's computer, the Claude app or claude.ai.

**Its key components:**

- **The instance:** `r7i.4xlarge`, Amazon Linux 2023, in its own VPC with no inbound access. Shell access
  is only through SSM Session Manager, and every session is logged.
- **The data volume:** 1 TB, encrypted, backed up weekly, mounted at `/srv/curation-data` and reached
  as the curator's `~/hca-tracker-upload`; downloads and curated files live there.
- **The instance role:** reads the tracker's data bucket and assumes the ODP writer role. Its S3 and STS
  calls are refused from outside the instance's VPC.
- **The curator:** runs Claude Code with Remote Control in tmux, started at boot by the
  `curation-remote-control` service, plus the MCP servers. It has no `sudo`.
- **`bootstrap.sh`:** installs and configures all of the above on the instance; safe to run again.
- **`make curation-on|off|status|shell|attach`:** the operator's commands, run on their own computer.

---

## 1. Users

### 1.1 `root`

- Runs `bootstrap.sh`, the systemd units and `dnf-automatic`.
- Owns everything outside the curator's home.

### 1.2 `ssm-user`

- The Session Manager user: the operator.
- Has `sudo` without a password.
- Runs admin shells, and nothing long-lived.

### 1.3 The curator (working user)

- The unprivileged user named by `CURATION_USER`, by default `curator`. This contract writes its home as `/home/curator`;
  with another name it is `/home/$CURATION_USER`.
- Runs Claude Code, its Remote Control session, the MCP servers and every download.
- Has no `sudo`. `bootstrap.sh` asks `sudo -l -U` and refuses to continue if it lists anything.
- Is untrusted:
    - it takes instructions through Remote Control;
    - it reads files downloaded from outside;
    - so anything it can write is treated as hostile by `root` and `ssm-user`.

## 2. Privileges, by role

### 2.1 `root`

2.1.1 Never writes inside the curator's home. `bootstrap.sh` is split by who runs it: its `root` part
touches only system paths, and it runs `setup-curator.sh` as the curator for everything in the curator's
home.

- No `>`, `>>`, `install`, `cp`, `mv`, `mkdir`, `chmod` or `chown` by `root` on a path under
  `/home/curator`.
- Files and folders there are created and changed by the curator: `setup-curator.sh`, which
  `bootstrap.sh` runs as the curator with `sudo -u`.

2.1.2 One exception to 2.1.1: setting the owner and mode of the home folder itself, whose parent,
`/home`, is `root`'s. `root` refuses if the home folder is a symlink.

- The data volume is not an exception. `root` mounts it at `/srv/curation-data`, under a parent `root`
  owns, and gives its top folder to the curator with commands that do not follow links. The curator's
  `~/hca-tracker-upload` is a link to it, which the curator makes.

2.1.3 Never reads, sources or runs a file the curator can write. `bootstrap.sh` refuses to run unless its
    folder, every folder above it and every file in it are `root`'s and writable by no one else.

2.1.4 Runs the curator's commands with arguments, never as a shell string built from values.

- Yes: `sudo -u curator -H env REPO_REF="$ref" bash setup-curator.sh`
- No: `sudo -u curator bash -c "git clone --branch $ref ..."`

2.1.5 Validates every value from `/etc/curation-workstation.conf` before substituting it into a unit, a
    script or a path.

### 2.2 `ssm-user`

2.2.1 Executes and sources only `root`'s files:

- the helper commands in `/usr/local/bin`;
- `/etc/curation-workstation.conf`.

2.2.2 Reaches the curator's session only through `curation-attach`, which runs
    `sudo -iu curator tmux attach`.

2.2.3 Never shares its terminal with a curator process. `sudo` runs each command in its own terminal
    (`use_pty`), so code the curator controls, started by `bootstrap.sh` or `curation-attach`, cannot type
    commands into the operator's.

### 2.3 The curator

2.3.1 Can write only its own home and the data volume.

2.3.2 Cannot change the controls that must hold against it. Those live outside its home, owned by `root`:

- Claude Code's deny rules, in its managed settings, `/etc/claude-code/managed-settings.json`. No user
  or project setting overrides them.
- Not in `~/.claude`, which the curator can edit.

2.3.3 Cannot become `root`: no `sudo`, no file `root` runs, and no path `root` writes through.

## 3. How this contract is enforced

3.1 The restrictions on `root` are rules about our code. The operating system cannot restrict `root`, so
    nothing stops a `root` process from breaking them except the code that `root` runs: `bootstrap.sh`.
    The restrictions on the curator are different: the operating system enforces them.

3.2 Each rule is met in one of four ways, strongest first:

- **Structure.** The code is arranged so the operating system enforces the rule.
- **A loud check.** The code stops with an error before breaking the rule.
- **A test.** A verification step attacks the rule and confirms it holds.
- **Review.** Code review checks changes against this contract. On its own this is the weakest, and a
  rule that relies only on review says so.

3.3 How each rule is met:

- **2.1.1, `root` never writes in the curator's home:**
    - structure: `bootstrap.sh`'s `root` part runs `setup-curator.sh` as the curator for everything in
      the curator's home, so those writes have only the curator's permissions;
    - a loud check: the `root` part's file helpers (`put_file`, `put_dir`) stop on any path under
      `/home/curator`;
    - a test: plant symlinks from the curator's home to system paths (`~/.claude` → `/etc`, `.env` →
      `/etc/shadow`, `~/.bashrc` → `/etc/ld.so.preload`), run `bootstrap.sh`, and confirm it refuses or
      writes only through the links as the curator, and that the system paths are unchanged.
- **2.1.2, the home-folder exception:** a loud check refuses the home folder if it is a symlink.
- **2.1.3, `root` never runs the curator's files:** structure: everything `root` and `ssm-user` execute
  is under `/usr/local/bin`, `/etc` or the unit, all `root`'s; a loud check: `bootstrap.sh` refuses to
  run from a folder anyone but `root` can change; review for any new path.
- **2.1.4, arguments, not shell strings:** review. `shellcheck` flags some cases, not all.
- **2.1.5, validated config values:** a loud check on each value against its expected form, before it
  is used.
- **2.2.3, a terminal of its own:** structure: `bootstrap.sh` installs `Defaults use_pty` in
  `/etc/sudoers.d/curation-use-pty`, checked with `visudo` first. A test: `sudo -l` lists `use_pty`.
- **1.3 and 2.3, the curator's limits:** the operating system: no `sudo` (a loud check with
  `sudo -l -U`), file permissions, and Claude Code's managed settings, which no user setting overrides.
  A test: as the curator, `sudo -n true` fails and `/etc/claude-code/managed-settings.json` cannot be
  changed.

## 4. Where things live

### 4.1 `root`'s

- Written by `bootstrap.sh`:
    - `/usr/local/bin/{aria2c,uv,uvx,curation-claude,curation-attach}`
    - `/etc/systemd/system/curation-remote-control.service`
    - `/etc/claude-code/managed-settings.json`
    - `/etc/sudoers.d/curation-use-pty`
    - `/etc/fstab`, `/etc/dnf/`
    - the mount point `/srv/curation-data`, whose contents are the curator's
- Written by the operator, by hand: `/etc/curation-workstation.conf`.

### 4.2 The curator's

- Everything under its home, written by the curator:
    - the clone, `~/hca-validation-tools`, with its `.mcp.json` and `.env`;
    - `~/.aws/config` and `~/.claude`;
    - the tmux socket the boot service and `curation-attach` share, `~/.tmux-claude`. It is not in `/tmp`,
    which is cleaned after 10 days.
- The data volume, mounted at `/srv/curation-data` and reached as `~/hca-tracker-upload`, a link the
  curator makes:
    - downloads land there, in the tracker client's cache, `~/hca-tracker-upload/.hca-tracker-cache`;
    - never on the 100 GB root volume.

### 4.3 One place per setting

- The region and the regional STS endpoint are in the curator's `~/.aws/config`.
- The AWS CLI and SDKs read it from a login shell and from the service alike.
- They are not repeated in units or shell profiles.

## 5. Secrets

### 5.1 The tracker token

- In the clone's `.env`, mode 600.
- Readable by the curator, since the tracker MCP server runs as that user.
- The managed deny on reading `.env` lowers the chance of the token reaching a transcript; it does not
  prevent it.
- Temporary: #892 replaces it with the instance's own AWS identity.

### 5.2 AWS

- No long-lived AWS keys on the machine. It uses the instance role.
- Uploads, when added, use short-lived IAM Identity Center credentials.

### 5.3 claude.ai

- The login lives in the curator's `~/.claude`.
- Whoever controls that account can run commands on the machine, so the account uses SSO or MFA.

## 6. Software

6.1 From the Amazon Linux repository:

- installed with `dnf`;
- security updates applied by `dnf-automatic`;
- dnf follows the latest repository version.

6.2 From outside it:

- pinned to a version and a SHA-256; the install refuses on a mismatch;
- a source build removes its compiler and `-devel` packages afterwards;
- listed in the README with its version, checksum and source.

6.3 Claude Code is the one exception to 6.2:

- Anthropic's installer checks the binary against its release manifest;
- Claude Code updates itself.

6.4 Python environments use CI's Python version, so the machine resolves the same wheels CI tests.

## 7. `bootstrap.sh`

7.1 Safe to run again:

- every step checks before it acts;
- each prints `ok`, `changed`, `synced` or `todo`;
- a second run on an unchanged machine reports 0 changes.

7.2 One input, `/etc/curation-workstation.conf`. Nothing on the command line or in the environment
    changes what it does.

7.3 `REPO_REF` is used for the first clone only. The clone is updated afterwards with `git pull`, as the
    curator.

7.4 A run that changes the boot service's unit or `curation-claude` restarts the service, so no change
    waits for the next boot. The restart ends the running Claude session, which comes back under the same
    name.

## 8. Data

8.1 Downloads are untrusted:

- Python that reads them runs with `-I`;
- scripts are kept outside the download folders.

8.2 Data leaves the machine only through:

- the tracker's upload tools;
- the ODP writer role.

## 9. The operator's commands

9.1 `make curation-*` reads the instance ID, the AWS profile and the region from `.env.make` only. As with
    the repo's deploy profiles, a profile given on the command line or in the environment stops the target.

9.2 The commands start, stop, report on, and open sessions to the instance. They change nothing on it.

---

## What is not true yet

- **3.3's symlink test is a manual step,** run once on the instance and listed in the pull request's
  "How to verify". Nothing runs it automatically.
- **5.1's token is still on the machine.** It stays until #892 lands, after the tracker's #1638.
- **8.1 is a practice, not a control.** Nothing stops a Python process reading a download without `-I`.
- **Nothing records what Remote Control runs where the machine cannot change it.** `auditd` and the
  CloudWatch agent come in stage C, after tf-config #92, and before real curation work.

## What this changes

- **`bootstrap.sh` splits in two.** Its `root` part keeps the system paths, with `put_file` and `put_dir`
  refusing any path under the curator's home. A new `setup-curator.sh`, run as the curator, does
  everything in the curator's home. *Done on this branch.*
- **The data volume moves to `/srv/curation-data`,** so mounting it is no longer an exception to 2.1.1.
  *Done on this branch.*
- **The `.env` deny moves out of `~/.claude/settings.json`** into the managed settings (2.3.2). *Done on
  this branch.*
- **The AWS settings stop being repeated** in `/etc/profile.d` and the unit (4.3). *Done on this branch.*
- **The tmux socket moves out of `/tmp`** (4.2). *Done on this branch.*
- **`sudo` gives each command its own terminal** (2.2.3). *Done on this branch.*
