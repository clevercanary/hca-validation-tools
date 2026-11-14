# Curation workstation

An EC2 instance for atlas curation. Claude Code runs on it with Remote Control,
so the same session can be driven from a terminal on your computer, the Claude
app and claude.ai. The instance, its network and its permissions are built by
the `curation-workstation` module in `hca-atlas-tracker-tf-config`; this folder
sets up what runs on it.

## What is here

| File | Purpose |
|---|---|
| `bootstrap.sh` | Sets up the instance's system side as root; safe to run again. It never writes in the curator's home. |
| `setup-curator.sh` | Sets up the curator's home. `bootstrap.sh` runs it as the curator. |
| `curation-workstation.conf.example` | The settings `bootstrap.sh` reads from `/etc/curation-workstation.conf`. |
| `curation-remote-control.service` | Template for the systemd unit that keeps Claude Code running in tmux. |
| `curation-claude.sh` | Installed as `/usr/local/bin/curation-claude`: runs Claude Code with Remote Control, restarting it if it exits. |
| `curation-attach.sh` | Installed as `/usr/local/bin/curation-attach`: attaches to that tmux session as the curator. |

## Using it from your computer

Add these to `.env.make` at the repo root (see `.env.make.example`): the
instance ID (Terraform output `instance_id`), an AWS profile allowed to start,
stop and open sessions on it, and the region.

```
CURATION_INSTANCE_ID=...
CURATION_AWS_PROFILE=...
CURATION_AWS_REGION=...
```

| Command | Does |
|---|---|
| `make curation-on` | Starts the instance and waits until it is running |
| `make curation-off` | Stops it |
| `make curation-status` | Shows its state and last start; when running, its data volume use |
| `make curation-shell` | Opens a Session Manager shell as `ssm-user` |
| `make curation-attach` | Attaches to the Claude Code session. Detach with `Ctrl-b d`; Claude keeps running. |

The Session Manager plugin must be installed on your computer
(`brew install --cask session-manager-plugin` on macOS). Session Manager closes
a session after 20 idle minutes; attach again when it does.

The session also appears under its Remote Control name in the Claude app and
on claude.ai, for whoever is signed in to the claude.ai account that logged in
on the instance.

## Users

- **`ssm-user`**: the Session Manager user, with `sudo`. Setup and other admin
  steps run as this user.
- **The curator** (the working user; `CURATION_USER`, by default `curator`): has no `sudo`.
  Claude Code, the boot service and the MCP servers run as this user, so a
  Claude session cannot become root. Its home folder is readable only by it.

## Setting up a new instance

1. `make curation-on`, then `make curation-shell`.
2. Get this folder onto the instance, as root, into a folder only root can
   change (`bootstrap.sh` refuses to run from anywhere else, such as `/tmp`),
   and write the settings:
   ```bash
   sudo dnf install -y git
   sudo git clone https://github.com/clevercanary/hca-validation-tools.git /opt/hca-validation-tools
   sudo cp /opt/hca-validation-tools/deployment/curation-workstation/curation-workstation.conf.example /etc/curation-workstation.conf
   sudo vi /etc/curation-workstation.conf
   ```
   To update the scripts later, run `sudo git -C /opt/hca-validation-tools pull`.
   Set `ODP_ROLE_ARN` to the ODP writer role (`odp-bucket-writer` Terraform
   output `role_arn`) and `ODP_PROFILE` to the profile name to use for it.
3. Run the bootstrap: `sudo /opt/hca-validation-tools/deployment/curation-workstation/bootstrap.sh`.
   It prints `ok`, `changed`, `synced` or `todo` for each step, then the
   number of changes. A second run reports 0 changes.
4. Put the tracker token in the curator's clone, readable only by the curator.
   Use a token made for the workstation on the tracker's `/api-token` page, not
   the one on your computer, so each expires on its own. Session Manager logs
   everything a session shows, so read the token without echoing it:
   ```bash
   sudo -iu curator
   cd ~/hca-validation-tools
   umask 077
   read -rsp 'Tracker API token: ' token; echo
   printf 'HCA_TRACKER_URL=%s\nHCA_TRACKER_API_TOKEN=%s\n' https://tracker.data.humancellatlas.org "$token" > .env
   unset token
   exit
   ```
   This is a 30-day token, so it is replaced every month. It goes away when
   `hca-tracker-client` authenticates with the instance's AWS credentials
   instead (hca-validation-tools#892).
5. Sign in Claude Code and turn on Remote Control, once: `curation-attach`
   (or `make curation-attach` from your computer). In the session, sign in with
   the claude.ai account, using its link and code. Answer yes to "Enable Remote
   Control?" and to trusting the folder. Then detach with `Ctrl-b d`.

   Anyone who controls that claude.ai account can run commands on the
   instance, so the account must use SSO or MFA.

From then on the boot service starts the session at every boot.

## What `bootstrap.sh` sets up

The rules it follows are in `docs/curation-workstation-contract.md`: root sets up
the machine, the curator owns its home, and root never writes inside it.
`bootstrap.sh` does the system side as root and runs `setup-curator.sh` as
the curator for everything in the curator's home.

- The curator, without `sudo`, with a private home folder.
- From the Amazon Linux repository: `tmux`, `git` and `dnf-automatic`, which
  applies security updates automatically (`upgrade_type = security`,
  `apply_updates = yes`), with dnf pointed at the latest repository version.
- aria2, uv and Claude Code (see the next section).
- The data volume (`DATA_DEVICE`) at `/srv/curation-data`, mounted by UUID
  with `nofail`, formatted as XFS only if it is blank, and given to the
  curator. An existing entry for it in `/etc/fstab` under another folder is
  moved. The curator reaches it as `~/hca-tracker-upload`, a link.
- The tracker client's download cache on the data volume
  (`~/hca-tracker-upload/.hca-tracker-cache`), since its default is on the
  100 GB root volume. Downloads refuse to start when the volume lacks room.
- This repo, cloned at `REPO_REF` into the curator's home (first run
  only; update it with `git pull` as the curator), with
  `uv sync` in `packages/hca-anndata-mcp` and `packages/hca-tracker-mcp`.
- The curator's `.mcp.json` (both MCP servers) and `~/.aws/config`: the
  region, regional STS endpoints, and the ODP writer profile, assumed with the
  instance's own credentials. Regional STS matters because the instance's
  credentials are refused for S3 and STS calls that do not go through its own
  VPC, and the global STS endpoint does not. Secret files are mode 600 and
  their folders 700. `bootstrap.sh` replaces these files when their content
  differs, so make lasting changes here, not on the instance.
- Claude Code's managed settings, `/etc/claude-code/managed-settings.json`:
  Claude's Read tool may not read `.env`. The file is root's, so the curator, and so a Claude session, cannot change it.
- `sudo`'s `use_pty`, in `/etc/sudoers.d/curation-use-pty`: every command
  `sudo` runs gets its own terminal, so a curator process started by
  `bootstrap.sh` or `curation-attach` cannot type into the operator's.
- The boot service, `curation-remote-control`, enabled and started. When a
  run changes its unit or `curation-claude`, `bootstrap.sh` restarts it,
  which ends the running Claude session; it comes back under the same name.

The deny on `.env` covers Claude's Read tool, not shell commands, so it lowers
the chance of the token reaching a transcript but does not prevent it. The
token must stay readable by the curator, since the tracker MCP server
runs as that user.

## Software from outside the Amazon Linux repository

Nothing updates these automatically. Watch their releases and security
advisories, change the pin in `bootstrap.sh`, and run it again.

| Software | Version | Check | Source |
|---|---|---|---|
| aria2 | 1.37.0 | SHA-256 `60a420ad7085eb616cb6e2bdf0a7206d68ff3d37fb5a956dc44242eb2f79b66b` of `aria2-1.37.0.tar.xz` | github.com/aria2/aria2 releases. Built from source, since Amazon Linux 2023 does not package it; the compiler and `-devel` packages it needs are removed after. |
| uv | 0.10.9, as in CI | SHA-256 `20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594` of `uv-x86_64-unknown-linux-gnu.tar.gz` | github.com/astral-sh/uv releases |
| Claude Code | latest at install, then self-updating | The installer checks the binary against the SHA-256 in its release manifest | `https://claude.ai/install.sh` |

`bootstrap.sh` refuses to install aria2 or uv when the download's checksum
differs from the pin.

## Smoke test

1. `make curation-status` shows `running` and the 1 TB volume.
2. `make curation-attach` shows the Claude Code session; detach with `Ctrl-b d`.
3. From the Claude app, open the session and ask it to run `hostname` and
   `df -h ~/hca-tracker-upload`. The instance and the 1 TB volume show.
4. Run `/mcp`. Both MCP servers are connected. Ask for `check_environment`.
5. Download one source dataset with `start_download`, then run
   `/evaluate-h5ad` on it. A report is written next to the file.
6. In a `make curation-shell` session, run `sudo reboot`. Within a few
   minutes, the session is back in the Claude app.
7. As the curator, `sudo -n true` fails.

## Not set up yet

- Uploading from the instance: an upload profile, `hca-smart-sync` and
  `s5cmd`. Uploads are to use short-lived Identity Center credentials, not
  long-lived keys.
- `gh`.
- The idle switch-off.
- `auditd` and the CloudWatch agent, which keep a record of what Remote
  Control runs that the instance cannot change. These come before real
  curation work.
