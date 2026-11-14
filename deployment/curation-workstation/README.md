# Curation workstation

An EC2 instance for atlas curation. Claude Code runs on it with Remote Control,
so the same session can be driven from a terminal on your computer, the Claude
app and claude.ai. The instance, its network and its permissions are built by
the `curation-workstation` module in `hca-atlas-tracker-tf-config`; this folder
sets up what runs on it, once, at the instance's first boot.

The rules it follows are in `docs/curation-workstation-contract.md`: the
instance is built once and replaced rather than changed, the data volume
outlives it, and no one can become root on it after first boot.

## What is here

| File | Purpose |
|---|---|
| `bootstrap.sh` | Sets up the instance as root at first boot, from the instance's `user_data`. Refuses a second run. |
| `setup-curator.sh` | Sets up the curator's home. `bootstrap.sh` runs it as the curator. |
| `curation-workstation.conf.example` | The form of `/etc/curation-workstation.conf`, which `user_data` writes from Terraform's values. |
| `curation-remote-control.service` | Template for the systemd unit that keeps Claude Code running in tmux. |
| `curation-claude.sh` | Installed as `/usr/local/bin/curation-claude`: runs Claude Code with Remote Control, restarting it if it exits. |
| `curation-attach.sh` | Installed as `/usr/local/bin/curation-attach`: attaches to that tmux session as the curator. |
| `curation-set-tracker-token.sh` | Installed as `/usr/local/bin/curation-set-tracker-token`: writes the tracker token to the curator's `.env`, for `make curation-set-tracker-token`. |
| `curation-status.sh` | Installed as `/usr/local/bin/curation-status`: reports the first boot's progress and the data volume's use, for `make curation-status`. |

## Using it from your computer

Add these to `.env.make` at the repo root (see `.env.make.example`): the
instance's Name tag, an AWS profile allowed to start, stop and open sessions
on it, and the region. The targets find the instance by its name, since each
replacement gives it a new ID.

```
CURATION_INSTANCE_NAME=...
CURATION_AWS_PROFILE=...
CURATION_AWS_REGION=...
```

| Command | Does |
|---|---|
| `make curation-on` | Starts the instance and waits until it is running |
| `make curation-off` | Stops it and waits until it has stopped |
| `make curation-status` | Shows its ID, state and last start; when running, whether first boot has finished, and its data volume use |
| `make curation-shell` | Opens a Session Manager shell as `ssm-user` |
| `make curation-attach` | Attaches to the Claude Code session. Detach with `Ctrl-b d`; Claude keeps running. |
| `make curation-set-tracker-token` | Prompts for the tracker API token, without echoing it, and puts it in the curator's `.env` |

The Session Manager plugin must be installed on your computer
(`brew install --cask session-manager-plugin` on macOS). Session Manager closes
a session after 20 idle minutes; attach again when it does.

The session also appears under its Remote Control name in the Claude app and
on claude.ai, for whoever is signed in to the claude.ai account that signed in
on the instance.

## Users

- **`ssm-user`**: the Session Manager user. It can become the curator with
  `sudo -iu curator`, and cannot become root.
- **`curator`**, the working user: has no `sudo`.
  Claude Code, the boot service and the MCP servers run as this user. Its home
  folder is readable only by it.

Nothing on the instance runs as root after first boot except the system's own
services. A problem that needs root is fixed in this repo and reaches the
instance by replacing it.

## How the instance is built

1. Terraform creates the instance. At its first boot, cloud-init runs its
   `user_data`, which writes `/etc/curation-workstation.conf`, clones this repo
   into `/opt/hca-validation-tools` at the pinned commit, checks the commit, and
   runs `bootstrap.sh`.
2. `make curation-status` shows `first boot started`, then `first boot done`
   with the commit, or `first boot failed`. The full output is in
   `/var/log/cloud-init-output.log` on the instance.
3. Terraform attaches the data volume after the instance starts;
   `bootstrap.sh` waits up to 5 minutes for it.
4. If `make curation-status` reports that `curation-status` is not found,
   first boot failed before `bootstrap.sh` started. The instance's console
   output (`aws ec2 get-console-output --latest` with your profile and region)
   shows why. Fix the cause and replace the instance.

**To change anything `bootstrap.sh` sets up**, including a pinned version:
change it here and merge it, put the new commit in the curation workstation's
tf-variables, and apply. A change to `user_data` replaces the instance. The
data volume, with downloads, curated files, scratch and Claude's conversation
logs, is reattached to the new instance.

A replacement loses what is on the root volume: the Claude sign-in, the tracker
token, and the curator's clone and its environments (rebuilt at first boot).

## After first boot, and after each replacement

1. Put the tracker token on the instance: `make curation-set-tracker-token`,
   and paste the token at the prompt. Use a token made for the workstation on
   the tracker's `/api-token` page, not the one on your computer, so each
   expires on its own. The prompt does not echo it, so the Session Manager log
   never shows it, and it is never a command-line argument. It goes into the
   curator's `~/hca-validation-tools/.env`, mode 600. If Claude is already
   running, run `/mcp` there to reconnect the tracker server. This is a 30-day token, so it is replaced every month. It goes away when
   `hca-tracker-client` authenticates with the instance's AWS credentials
   instead (hca-validation-tools#892).
2. Sign in Claude Code and turn on Remote Control: `make curation-attach`. In
   the session, sign in with the claude.ai account, using its link and code.
   Answer yes to "Enable Remote Control?" and to trusting the folder. Then
   detach with `Ctrl-b d`.

   Anyone who controls that claude.ai account can run commands on the
   instance, so the account must use SSO or MFA.

From then on the boot service starts the session at every boot.

The curator may update its own clone with `git switch main && git pull`, and
`uv sync` in each MCP server's folder. A replacement resets it to the pinned
commit.

## What `bootstrap.sh` sets up

`bootstrap.sh` does the system side as root and runs `setup-curator.sh` as
the curator for everything in the curator's home.

- The curator, with a fixed UID (`CURATION_UID`) so its files on the data
  volume keep their owner across replacements, and a private home folder.
  First boot stops if a volume from an earlier instance belongs to another
  UID; set `CURATION_UID` to that UID.
- `ssm-user`, created before the SSM agent would create it, with one sudoers
  rule (`/etc/sudoers.d/ssm-agent-users`): it may run commands as the curator.
  `sudo`'s `use_pty` (`/etc/sudoers.d/curation-use-pty`) gives each of those
  commands its own terminal, so a curator process cannot type into the
  operator's. Both files are checked with `visudo` before they are installed.
- The image's `ec2-user`, locked, and its cloud-init sudoers file removed,
  since that user could become root.
- From the Amazon Linux repository: `tmux`, `git`, `python3.11` (CI's
  Python, which uv uses instead of downloading one) and `dnf-automatic`, which
  applies security updates automatically (`upgrade_type = security`,
  `apply_updates = yes`), with dnf pointed at the latest repository version.
- aria2, uv and Claude Code (see the next section).
- The data volume, found by its EBS volume ID (`DATA_VOLUME_ID`), so no
  other disk can be taken for it, at `/srv/curation-data`, mounted by UUID
  with `nofail`, `nosuid` and `nodev`, and formatted as XFS only if it holds no filesystem. The
  curator reaches it as `~/hca-tracker-upload`, a link. On it:
    - the tracker client's download cache, `~/hca-tracker-upload/.hca-tracker-cache`,
      since its default is on the 100 GB root volume;
    - scratch, `~/hca-tracker-upload/tmp`, for Claude Code and the commands it
      runs; files older than 10 days are removed;
    - Claude's conversation logs, `~/hca-tracker-upload/.claude-projects`,
      reached as `~/.claude/projects`.
- This repo, cloned at the pinned commit into the curator's home, with
  `uv sync` in `packages/hca-anndata-mcp` and `packages/hca-tracker-mcp`.
- The curator's `.mcp.json` (both MCP servers) and `~/.aws/config`: the
  region, regional STS endpoints, and the ODP writer profile, assumed with the
  instance's own credentials. Regional STS matters because the instance's
  credentials are refused for S3 and STS calls that do not go through its own
  VPC, and the global STS endpoint does not. The curator's files are mode 600
  and its folders 700.
- Claude Code's managed settings, `/etc/claude-code/managed-settings.json`:
  Claude's Read tool may not read `.env`. The file is root's, so the curator,
  and so a Claude session, cannot change it.
- The boot service, `curation-remote-control`, enabled and started, with
  `TMPDIR` set to the scratch folder for Claude Code and everything it runs.

The deny on `.env` covers Claude's Read tool, not shell commands, so it lowers
the chance of the token reaching a transcript but does not prevent it. The
token must stay readable by the curator, since the tracker MCP server
runs as that user.

## Software from outside the Amazon Linux repository

Nothing updates these automatically. Watch their releases and security
advisories, change the pin in `bootstrap.sh`, and replace the instance.

| Software | Version | Check | Source |
|---|---|---|---|
| aria2 | 1.37.0 | SHA-256 `60a420ad7085eb616cb6e2bdf0a7206d68ff3d37fb5a956dc44242eb2f79b66b` of `aria2-1.37.0.tar.xz` | github.com/aria2/aria2 releases. Built from source, since Amazon Linux 2023 does not package it; the compiler and `-devel` packages it needs are removed after. |
| uv | 0.10.9, as in CI | SHA-256 `20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594` of `uv-x86_64-unknown-linux-gnu.tar.gz` | github.com/astral-sh/uv releases |
| Claude Code | latest at install, then self-updating | The installer checks the binary against the SHA-256 in its release manifest | `https://claude.ai/install.sh` |

`bootstrap.sh` refuses to install aria2 or uv when the download's checksum
differs from the pin.

## Smoke test

1. `make curation-status` shows `running`, `first boot done` and the 1 TB volume.
2. `make curation-attach` shows the Claude Code session; detach with `Ctrl-b d`.
3. From the Claude app, open the session and ask it to run `hostname` and
   `df -h ~/hca-tracker-upload`. The instance and the 1 TB volume show.
4. Run `/mcp`. Both MCP servers are connected. Ask for `check_environment`.
5. Download one source dataset with `start_download`, then run
   `/evaluate-h5ad` on it. A report is written next to the file.
6. In a `make curation-shell` session, `sudo -n true` fails and
   `sudo -u curator true` succeeds.
7. Stop and start the instance. Within a few minutes, the session is back in
   the Claude app.

## Not set up yet

- Uploading from the instance: an upload profile, `hca-smart-sync` and
  `s5cmd`. Uploads are to use short-lived Identity Center credentials, not
  long-lived keys.
- `gh`.
- The idle switch-off.
- `auditd` and the CloudWatch agent, which keep a record of what Remote
  Control runs that the instance cannot change. These come before real
  curation work.
