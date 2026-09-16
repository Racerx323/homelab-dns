# Follow-up: fleet msmtp audit and standardization

This is a planning prompt, not authorization to deploy a fleet configuration.
The current configuration authority is `homelab-dns/msmtp`; older examples in
other repositories are historical references, not the fleet standard.

## Copyable prompt

Audit and plan standardization of the fleet's msmtp configuration using
`/home/aaron/code/homelab-dns/msmtp` as the owning component. Read applicable
`AGENTS.md` instructions, then inspect:

- `msmtp/configs/msmtprc`
- `msmtp/configs/msmtp_aliases`
- `msmtp/docs/msmtp-secrets-configuration.md`
- `msmtp/docs/add-msmtp-account.md`
- `msmtp/scripts/separate-msmtp-secret.sh`
- `msmtp/scripts/add-msmtp-account.sh`
- The relevant host inventory and consumer notification contracts.
- Mailrise/Apprise routing documentation in `homelab-notification/apprise-api`.
- `homelab-server-configs/smartmontools/docs/ALERT_DELIVERY.md` for the consumer
  hook and notification-verification requirements.

First prepare a repository-based candidate inventory and audit plan. Identify
the exact hosts and read-only probes before requesting live audit authorization,
unless that scope has already been explicitly granted in this session. Fleet
deployment, secret migration, account/default changes, package installation,
service lifecycle changes and test notifications are separate execution scopes.
Do not run either migration helper merely to inspect a host.

This is an independent workstream. Do not resume the Nautobot storage investigation,
alter smartd monitoring policy, re-enable Webmin polling or perform host-storage
fleet qualification. Fleet-wide standardization is not a prerequisite for
Nautobot host acceptance when its own required notification routes are verified.
Do not infer live audit authorization from the earlier single-host repair.

### Required audit and plan

1. For each selected host, identify OS/version, installed msmtp/msmtp-mta and
   mail-frontend packages, sendmail/mail alternatives, system and per-user
   configuration precedence, account inheritance, default account, aliases,
   executable hooks, invoking service identities and secret access requirements.
   Label missing or stale facts. Preserve legitimate host-specific accounts.

2. Compare effective configuration with the current owner templates. Keep
   differences in a sanitized matrix: desired, observed, reason, owner and
   proposed disposition. Do not print passwords, secret-file contents or
   credential-bearing commands. For secrets, record reference, existence,
   ownership, permissions and authorized-reader properties only.

3. Map each consumer (smartd, cron, needrestart and other installed senders)
   through its actual invocation, selected msmtp account, alias-resolved
   recipient, SMTP endpoint and intended final destination. Test cases must
   distinguish email delivery from Apprise notification delivery.

4. Resolve account-selection/alias interactions before deployment. The current
   template selects `mailgun` by default while the alias template maps `root`
   to `notify@mailrise.xyz`. A recipient alias does not select an SMTP account.
   Establish the intended effective route for each consumer; do not assume
   copying both files makes every root-run sender use Mailrise. Propose explicit
   account selection or reviewed profile differences where needed, preserving
   intended external email and notification behavior.

5. Define reusable configuration profiles and explicit per-host selection.
   Keep shared implementation in this component and consumer policy with its
   owner. Audit dependent scripts and older documentation for conflicting
   defaults; replace duplicate guidance with owner references where appropriate.
   Do not change unrelated DNS, HA, storage or application configuration.

6. Review the existing helpers against the fleet's actual Debian releases.
   Their current documentation targets Debian 12; verify compatibility before
   proposing use on Debian 13. Keep interactive secret entry separate from
   unattended configuration deployment. Do not rotate credentials incidentally.

7. Prepare a one-host pilot with exact configuration diffs, package simulation,
   protected backup/rollback, metadata preservation, secret references, hashed
   non-secret execution inputs, drift guards and explicit acceptance criteria.
   Exercise local fixtures before live changes; preserve all unrelated accounts.

8. Verify real consumer delivery in layers: configuration parsing, recipient and
   account selection, hook result, sendmail/msmtp child result, relay routing,
   downstream provider result and actual receipt. An SMTP success can coexist
   with a Mailrise recipient rejection. Use distinct labeled tests under sending
   authorization; do not spam recipients or declare success without receipt.

9. Plan serial per-host rollout after pilot acceptance. Account for HA/service
   dependencies, stop on failed delivery or unreviewed drift, and retain exact
   per-host recovery and terminal evidence. A working pilot is not fleet acceptance.

### Handoff from the smartd repair

The storage pilot's alert path was repaired by installing the missing mail
frontend and changing only smartd's recipient to the confirmed Mailrise notify
route. The existing older msmtp configuration and shared aliases were preserved.
End-to-end receipt was confirmed, but no fleet msmtp migration was performed.
Treat that recipient override as an explicit migration input: changing the
default SMTP account must not silently reroute its working notifications.

The repair added `bsd-mailx` and its `liblockfile-bin` / `liblockfile1` dependencies;
the existing `msmtp` and `msmtp-mta` packages and account configuration were retained.
Resolve current candidates per target rather than pinning every host to the pilot's
versions. Preserve the working smartd route through migration and qualify other
consumers independently; one successful smartd test does not validate cron or
needrestart delivery. Do not automatically choose the storage pilot as the fleet
migration pilot while its separate storage acceptance remains open.

Private evidence, if retained, is under
`/home/aaron/code/.local-evidence/smartd-investigation-20260916/`.
Do not copy raw logs, host identities or credentials into public evidence.

### Deliverables

Save the sanitized audit matrix, profile/ownership decisions, implementation gaps,
pilot operation proposal, test matrix and serial rollout/rollback plan in this
component's documentation. Separate repository findings, authorized live findings
and unverified assumptions. Finish with the next concrete authorized stage and
any missing decisions. Do not deploy, send test notifications, commit or push
under this planning prompt alone.

Make the pilot proposal usable as the next handoff: name its target and why it
was chosen, enumerate affected consumers, list exact proposed changes and rollback
inputs, and specify the remaining authorization. Record blockers separately for
audit, implementation, pilot deployment and fleet rollout so work can continue
without confusing a deferred deployment with an incomplete repository audit.
