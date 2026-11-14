# Curation Workstation Contract

## Keeping the workstation secure: built once, replaced rather than changed

**Status:** Draft — assertions under discussion
**Date:** 2026-11-13
**Prompted by:** the review of #875 stage A. Making `bootstrap.sh` safe to re-run as `root` on a machine
the curator had used took a guard for every path; building the machine once removes the need for them.

The instance is built once, at first boot, and replaced rather than changed. The data volume outlives
every instance. `root` sets the machine up before the curator has run anything, and no one can become
`root` on it afterwards.

## Overview

**What it is.** A prod EC2 instance for atlas curation, built by the `curation-workstation` module in
`hca-atlas-tracker-tf-config` and set up at its first boot by `deployment/curation-workstation/` in this
repo.

**What it is for.** Running the atlas work done on a laptop today, `/evaluate-h5ad`, `/curate-h5ad` and
the tracker and AnnData MCP servers, on a large machine with a large disk, driven by Claude Code from a
terminal on the operator's computer, the Claude app or claude.ai.

**Its key components:**

- **The instance:** `r7i.4xlarge`, Amazon Linux 2023, in its own VPC with no inbound access. Shell access
  is only through SSM Session Manager, and every session is logged. Disposable: everything on its root
  volume is lost when it is replaced.
- **The data volume:** its own entity, not part of the instance.
    - A separate Terraform resource, `aws_ebs_volume.data`, with `prevent_destroy`, joined to the
      instance by a separate `aws_volume_attachment`. Replacing the instance replaces only the attachment.
    - 1 TB, encrypted, snapshotted weekly.
    - Mounted at `/srv/curation-data` and reached as the curator's `~/hca-tracker-upload`; downloads and
      curated files live there.
- **The instance role:** reads the tracker's data bucket and assumes the ODP writer role. Its S3 and STS
  calls are refused from outside the instance's VPC.
- **The curator:** runs Claude Code with Remote Control in tmux, started at boot by the
  `curation-remote-control` service, plus the MCP servers. It has no `sudo`.
- **First boot:** cloud-init runs the instance's `user_data`, which writes the settings, clones this repo
  at a pinned commit and runs `bootstrap.sh`.
- **`make curation-on|off|status|shell|attach`:** the operator's commands, run on their own computer.

---

## 1. Lifecycle

### 1.1 Built once

- At the instance's first boot, cloud-init runs its `user_data`, which Terraform writes:
    - writes `/etc/curation-workstation.conf` from Terraform's values;
    - clones this repo into `/opt/hca-validation-tools` as `root`, at a pinned commit SHA, and stops if
      `HEAD` is not that commit;
    - runs `bootstrap.sh`.
- cloud-init runs `user_data` once per instance, not at later boots.

### 1.2 Replaced, not changed

- `bootstrap.sh` refuses to run a second time on the same instance.
- To change anything `bootstrap.sh` sets up, change it in this repo, put the new commit in tf-variables,
  and apply. A change to `user_data` replaces the instance (`user_data_replace_on_change`).
- The replacement starts from the latest Amazon Linux 2023 image. A newer image alone does not replace
  the instance.

### 1.3 What survives a replacement

- The data volume and everything on it, including Claude's conversation logs and its memory files (5.2).
  A replacement therefore does not clean up after a compromised curator: recovering from one also means
  reviewing or removing `.claude-projects`, whose memory files load into the next session.
- Nothing on the root volume: the Claude sign-in, the tracker token, and the curator's clone and its
  environments.

### 1.4 What the operator redoes after a replacement

- Puts the tracker token in the curator's `.env` (until #892).
- Signs in to claude.ai through `curation-attach`, and accepts the Remote Control and trust prompts.

### 1.5 What changes on a running instance

- Security updates, applied by `dnf-automatic`.
- Claude Code, which updates itself.
- The curator's own clone, which the curator may update with `git pull` and `uv sync`. A replacement
  resets it to the pinned commit.
- Nothing else. `root` does not change the machine after first boot.

## 2. Users

### 2.1 `root`

- Runs cloud-init and `bootstrap.sh` at first boot, then the systemd units, `dnf-automatic` and the SSM
  agent.
- Owns everything outside the curator's home and the data volume.
- After first boot, no person reaches it from the machine: `ssm-user` cannot `sudo` to it (3.2.4), and
  `bootstrap.sh` removes the image's `ec2-user` and its cloud-init sudoers file.
- The one route left is SSM Run Command (`AWS-RunShellScript`), which runs as `root`. It needs
  `ssm:SendCommand` in the AWS account, a permission that can already replace the instance.

### 2.2 `ssm-user`

- The Session Manager user: the operator.
- Can become the curator with `sudo -u`, without a password. Cannot become `root`.
- Runs shells, and nothing long-lived.

### 2.3 The curator (working user)

- The unprivileged user `curator`, with its home at `/home/curator`.
- Has a fixed UID, set in Terraform, so the files on the data volume keep their owner across
  replacements. `bootstrap.sh` stops if a volume from an earlier instance belongs to another UID, rather
  than changing the owner of what the curator wrote.
- Runs Claude Code, its Remote Control session, the MCP servers and every download.
- Has no `sudo`.
- Is untrusted:
    - it takes instructions through Remote Control;
    - it reads files downloaded from outside;
    - so anything it can write is treated as hostile by `ssm-user`, and `root` finishes its work before
      the curator runs anything.
- Scratch files, Claude's own and those of the commands it runs, go to the data volume (5.2).

## 3. Privileges, by role

### 3.1 `root`

3.1.1 Sets the machine up once, at first boot, before the curator has run anything.

3.1.2 Sets up the curator's home by running `setup-curator.sh` as the curator, with `sudo -u`, so:

- the curator's files belong to the curator;
- the tools that run code from outside, `git` and `uv sync`'s build backends, never run as `root`.

3.1.3 Runs only files it owns: the clone in `/opt`, which it made at the pinned commit.

3.1.4 Runs the curator's commands with arguments, never as a shell string built from values.

- Yes: `sudo -u curator -H env REPO_COMMIT="$commit" bash setup-curator.sh`
- No: `sudo -u curator bash -c "git -C ~/hca-validation-tools checkout $commit"`

3.1.5 Reads `/etc/curation-workstation.conf` as `KEY=value` lines and never sources it, so no value runs
    as a command. Validates every value before substituting it into a unit, a script or a path.

3.1.6 Finds the data volume by its EBS volume ID, the disk's serial number, so no other disk can be taken
    for it. Formats it only if it holds no filesystem. A volume with one is mounted as it is.

### 3.2 `ssm-user`

3.2.1 Executes only `root`'s files: the helper commands in `/usr/local/bin`.

3.2.2 Reaches the curator's session only through `curation-attach`, which runs
    `sudo -iu curator tmux attach`.

3.2.3 Never shares its terminal with a curator process. `sudo` runs each command in its own terminal
    (`use_pty`), so code the curator controls cannot type commands into the operator's.

3.2.4 Cannot become `root`. The SSM agent creates `ssm-user` at the first session and gives it full
    `sudo` in `/etc/sudoers.d/ssm-agent-users`. `bootstrap.sh` creates `ssm-user` first and writes that
    file itself, with one rule:

- `ssm-user ALL=(curator) NOPASSWD: ALL`, so `curation-attach` and the operator's steps as the curator
  still work.
- A problem that needs `root` is fixed in this repo and reaches the machine by replacement (1.2).

### 3.3 The curator

3.3.1 Can write only its own home and the data volume.

3.3.2 Cannot change the controls that must hold against it. Those live outside its home, owned by `root`:

- Claude Code's deny rules, in its managed settings, `/etc/claude-code/managed-settings.json`. No user
  or project setting overrides them.
- Not in `~/.claude`, which the curator can edit.

3.3.3 Cannot become `root`: no `sudo`, and no file that `root` runs.

## 4. How this contract is enforced

4.1 The restrictions on `root` are rules about our code. The operating system cannot restrict `root`, so
    nothing stops a `root` process from breaking them except the code that `root` runs: `user_data` and
    `bootstrap.sh`. The restrictions on the curator are different: the operating system enforces them.

4.2 Each rule is met in one of four ways, strongest first:

- **Structure.** The code is arranged so the operating system, cloud-init or Terraform enforces the rule.
- **A loud check.** The code stops with an error before breaking the rule.
- **A test.** A verification step attacks the rule and confirms it holds.
- **Review.** Code review checks changes against this contract. On its own this is the weakest, and a
  rule that relies only on review says so.

4.3 How each rule is met:

- **1.1 and 3.1.1, built once, before the curator runs anything:**
    - structure: cloud-init runs `user_data` once per instance, and the curator does not exist until
      `bootstrap.sh` creates it;
    - a loud check: `bootstrap.sh` writes `/var/lib/curation-workstation/bootstrapped` when it starts,
      and refuses to start if the file exists, so a failed first boot is not retried on the same
      instance either.
- **1.2, replaced, not changed:** structure: `user_data_replace_on_change` in Terraform.
- **3.1.2, the curator's home set up as the curator:** structure: `setup-curator.sh` runs under
  `sudo -u`, so its writes have only the curator's permissions.
- **3.1.3, `root` runs only its own files:** a loud check: `user_data` stops if the clone's `HEAD` is not
  the pinned commit.
- **3.1.4, arguments, not shell strings:** review. `shellcheck` flags some cases, not all.
- **3.1.5, validated config values:** a loud check on each value against its expected form, before it
  is used.
- **3.1.6, the right volume, formatted only if blank:** structure: Terraform writes the volume's ID, and
  `bootstrap.sh` builds the disk's `/dev/disk/by-id/` path from it and accepts no other input. Loud checks: it formats
  only when `blkid` finds no filesystem, and, as a backstop, stops if the device has partitions or
  anything on it is mounted, as the root disk would. A test: replace the instance and confirm the volume's files are intact.
- **3.2.3, a terminal of its own:** structure: `bootstrap.sh` installs `Defaults use_pty` in
  `/etc/sudoers.d/curation-use-pty`, checked with `visudo` first. A test: `sudo -l` lists `use_pty`.
- **3.2.4, `ssm-user` cannot become `root`:**
    - structure: `bootstrap.sh` writes `/etc/sudoers.d/ssm-agent-users` with the curator-only rule,
      checked with `visudo` first;
    - a test: after the first session, as `ssm-user`, `sudo -n true` fails and `sudo -u curator true`
      succeeds.
- **2.3 and 3.3, the curator's limits:** the operating system: a new user has no `sudo`, file
  permissions, and Claude Code's managed settings, which no user setting overrides. A test: as the
  curator, `sudo -n true` fails and `/etc/claude-code/managed-settings.json` cannot be changed.

## 5. Where things live

### 5.1 `root`'s

- Written by `user_data`:
    - `/etc/curation-workstation.conf`, from Terraform's values;
    - `/opt/hca-validation-tools`, the clone at the pinned commit.
- Written by `bootstrap.sh`:
    - `/usr/local/bin/{aria2c,uv,uvx,curation-claude,curation-attach,curation-status}`
    - `/etc/systemd/system/curation-remote-control.service`
    - `/etc/claude-code/managed-settings.json`
    - `/etc/sudoers.d/curation-use-pty`, `/etc/sudoers.d/ssm-agent-users`
    - `/etc/tmpfiles.d/curation-scratch.conf`
    - `/etc/fstab`, `/etc/dnf/`
    - `/var/lib/curation-workstation/bootstrapped`, the first boot's record: started, then done or failed
    - the mount point `/srv/curation-data`, whose contents are the curator's

### 5.2 The curator's

- Everything under its home, written by the curator:
    - the clone, `~/hca-validation-tools`, with its `.mcp.json` and `.env`;
    - `~/.aws/config` and `~/.claude`;
    - the tmux socket the boot service and `curation-attach` share, `~/.tmux-claude`. It is not in `/tmp`,
      which is cleaned after 10 days.
- The data volume, mounted at `/srv/curation-data` and reached as `~/hca-tracker-upload`, a link the
  curator makes:
    - downloads land there, in the tracker client's cache, `~/hca-tracker-upload/.hca-tracker-cache`,
      never on the 100 GB root volume;
    - Claude's conversation logs live there, in `~/hca-tracker-upload/.claude-projects`, reached as
      `~/.claude/projects`, a link the curator makes. They survive a replacement, and the volume's weekly
      snapshots back them up.
    - scratch lives there, in `~/hca-tracker-upload/tmp`, a folder the curator makes. systemd-tmpfiles
      removes files in it older than 10 days, as it does in `/tmp`.
- The Claude sign-in stays in `~/.claude` on the root volume, so a replacement ends it (1.4).

### 5.3 One place per setting

- Every setting `bootstrap.sh` uses is set in Terraform (tf-variables); `/etc/curation-workstation.conf`
  is written from it and not edited by hand.
- The scratch folder is set once, as `TMPDIR=/srv/curation-data/tmp` in the boot service's unit. Claude
  Code, the commands it runs and the MCP servers inherit it.
- The region and the regional STS endpoint are in the curator's `~/.aws/config`. The AWS CLI and SDKs
  read it from a login shell and from the service alike. They are not repeated in units or shell
  profiles.

## 6. Secrets

### 6.1 The tracker token

- In the clone's `.env`, mode 600, put there by the operator after each replacement.
- Readable by the curator, since the tracker MCP server runs as that user.
- The managed deny on reading `.env` lowers the chance of the token reaching a transcript; it does not
  prevent it.
- Temporary: #892 replaces it with the instance's own AWS identity.

### 6.2 AWS

- No long-lived AWS keys on the machine. It uses the instance role.
- Uploads, when added, use short-lived IAM Identity Center credentials.

### 6.3 claude.ai

- The sign-in lives in the curator's `~/.claude`.
- Whoever controls that account can run commands on the machine, so the account uses SSO or MFA.

### 6.4 Not in `user_data`

- `user_data` holds no secret. Anyone who can describe the instance can read it.

## 7. Software

7.1 From the Amazon Linux repository:

- installed with `dnf`;
- security updates applied by `dnf-automatic`;
- dnf follows the latest repository version.

7.2 From outside it:

- pinned to a version and a SHA-256; the install refuses on a mismatch;
- a source build removes its compiler and `-devel` packages afterwards;
- listed in the README with its version, checksum and source;
- a new version reaches the instance through a new commit, a new pin and a replacement (1.2).

7.3 Claude Code is the one exception to 7.2:

- Anthropic's installer checks the binary against its release manifest;
- Claude Code updates itself.

7.4 Python environments use CI's Python version, 3.11, from the Amazon Linux repository; uv never
    downloads a Python. Their dependencies are resolved at first boot, as CI resolves them, since the
    packages' locks are not committed.

## 8. `bootstrap.sh`

8.1 Runs once, at first boot, from `user_data`. Its output is in `/var/log/cloud-init-output.log`.

8.2 Stops at the first error. A failed first boot leaves the instance unfinished: fix the cause in this
    repo and replace the instance.

8.3 One input, `/etc/curation-workstation.conf`. Nothing on the command line or in the environment
    changes what it does.

8.4 Waits for the data volume, which Terraform attaches after the instance starts, and fails if it has
    not appeared within 5 minutes.

## 9. Data

9.1 Downloads are untrusted:

- Python that reads them runs with `-I`;
- scripts are kept outside the download folders.

9.2 Data leaves the machine only through:

- the tracker's upload tools;
- the ODP writer role.

## 10. The operator's commands

10.1 `make curation-*` reads the instance's name, the AWS profile and the region from `.env.make` only. As
     with the repo's deploy profiles, a profile given on the command line or in the environment stops the
     target.

10.2 The commands start, stop, report on, and open sessions to the instance. They change nothing on it, and
     none uses Run Command: each needs only `ssm:StartSession` on the instance, beside starting and
     stopping it.

---

## What is not true yet

- **A first boot that fails early keeps the image's defaults.** If it fails before `bootstrap.sh` has
  removed `ec2-user` and restricted `ssm-user`, `ec2-user` keeps cloud-init's `sudo` and the SSM agent
  gives `ssm-user` full `sudo` at the first session. A failure in `user_data`'s own steps (installing
  `git`, the clone, the checkout or the commit check) also leaves `curation-status` missing. No curator exists and nothing from outside has run, so nothing untrusted
  can use that. `aws ec2 get-console-output` shows the error; fix its cause and replace the instance.
- **6.1's token is still on the machine.** It stays until #892 lands, after the tracker's #1638.
- **9.1 is a practice, not a control.** Nothing stops a Python process reading a download without `-I`.
- **Nothing records what Remote Control runs where the machine cannot change it.** `auditd` and the
  CloudWatch agent come in stage C, after tf-config #92, and before real curation work.
- **Three assumptions wait for the first-boot test:** that the SSM agent leaves a
  `/etc/sudoers.d/ssm-agent-users` it finds in place; that Claude Code writes its logs through the
  `~/.claude/projects` link; and that `/tmp` on Amazon Linux 2023 is in memory, the reason scratch moves.
- **How long a first boot takes has not been measured.** The aria2 source build and `uv sync` are the
  slow steps.

## What this changes

Against the earlier draft of this contract, in which `bootstrap.sh` was re-run on the live machine:

- **`bootstrap.sh` runs once, from `user_data`,** and refuses a second run. Changes arrive by replacement.
- **The guards that made re-running safe go:** the refusal to write under the curator's home, the
  symlink checks, the ownership check on the script's folder, the `ok`/`changed` counting, moving an
  existing `fstab` entry, and restarting the service when its files change.
- **The settings come from Terraform,** not a hand-written `/etc/curation-workstation.conf`.
- **The curator has a fixed UID,** so its files on the data volume keep their owner.
- **Claude's conversation logs move to the data volume,** so a replacement keeps them.
- **Scratch moves to the data volume,** out of `/tmp`, and is cleaned after 10 days.
- **`ssm-user` loses `root`.** It can become the curator only.
- **Kept from the earlier draft:** `setup-curator.sh` run as the curator, the data volume at
  `/srv/curation-data`, the managed `.env` deny, one place per setting, the tmux socket out of `/tmp`,
  and `use_pty`.
