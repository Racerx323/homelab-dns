# msmtp secrets configuration

This guide explains how to remove an SMTP password from the system-wide
`/etc/msmtprc` file on Debian 12. The password is stored in a separate file and
read at runtime with the msmtp `passwordeval` directive.

Separating the password has two benefits:

- `/etc/msmtprc` can be deployed from source control without containing a
  credential.
- File permissions can restrict the password to only the users and services
  that send mail.

This approach protects the password with Unix ownership and permissions. It
does not encrypt the password at rest. Root can still read the secret.

## Automated setup

The repository includes a Debian 12 helper that performs the password prompt,
permission setup, secret installation, and `msmtprc` rewrite:

```bash
sudo ./homelab-dns/msmtp/scripts/separate-msmtp-secret.sh \
  --account mailgun \
  --user pi
```

The password is read twice from `/dev/tty` without being displayed. The script
removes active and commented `password` or `passwordeval` directives from the
selected account and installs one `passwordeval` directive. It does not accept
a password through command-line arguments or standard input.

Run it with `--root-only` instead of `--user` when only root-run jobs should
read the secret:

```bash
sudo ./homelab-dns/msmtp/scripts/separate-msmtp-secret.sh \
  --account mailgun \
  --root-only
```

Use `--help` to see custom configuration path, secret path, group, and
multiple-user options. The default configuration path is `/etc/msmtprc`, so
the command must be executed on the Debian host where msmtp is installed.

## Prerequisites

Install msmtp and the system certificate bundle:

```bash
sudo apt-get update
sudo apt-get install msmtp msmtp-mta ca-certificates
```

Confirm which configuration paths the installed msmtp build uses:

```bash
msmtp --version
```

On Debian 12, the normal system-wide configuration path is `/etc/msmtprc`.
Per-user configurations are normally `~/.msmtprc` or
`~/.config/msmtp/config`.

## Replace the inline password

Find the SMTP account in `msmtprc`. An account with an inline password might
look like this:

```ini
account mailgun
host smtp.mailgun.org
port 587
from system@example.com
user system@example.com
password REPLACE_WITH_SECRET
```

Remove the `password` directive and replace it with:

```ini
passwordeval "/usr/bin/cat /etc/msmtp/secrets/mailgun-password"
```

The resulting account should resemble:

```ini
account mailgun
host smtp.mailgun.org
port 587
from system@example.com
user system@example.com
passwordeval "/usr/bin/cat /etc/msmtp/secrets/mailgun-password"
```

Use a different secret filename for each authenticated SMTP account. Do not
put the password itself, a command containing the password, or the secret file
inside the Git repository.

The Mailrise account does not need a secret when it contains both of these
directives:

```ini
auth off
tls off
```

`auth off` tells msmtp not to perform SMTP authentication, so no `password` or
`passwordeval` directive is required for that account.

## Option 1: root-only secret

Use this option when only root-run jobs and services send through the
authenticated SMTP account.

Create a root-only directory and an empty secret file:

```bash
sudo install -d -o root -g root -m 700 /etc/msmtp/secrets
sudo install -o root -g root -m 600 /dev/null \
  /etc/msmtp/secrets/mailgun-password
```

Edit the secret without placing it in shell history or command-line arguments:

```bash
sudoedit /etc/msmtp/secrets/mailgun-password
```

Enter only the SMTP password on one line, save the file, and exit the editor.
Do not use a command such as `echo 'password' > file`; the password could be
retained in shell history, process information, terminal logs, or automation
logs.

Reassert the intended ownership and permissions:

```bash
sudo chown root:root /etc/msmtp/secrets/mailgun-password
sudo chmod 600 /etc/msmtp/secrets/mailgun-password
```

With this setup, a non-root process cannot use the authenticated SMTP account
because `/usr/bin/cat` runs as the same user that invoked msmtp.

## Option 2: allow selected service users

Use a dedicated group when one or more non-root services must send mail. Avoid
making the secret world-readable.

Create a system group:

```bash
sudo addgroup --system msmtp-secrets
```

Add each authorized account to the group. Replace `SERVICE_USER` with the
actual Debian account used by the application or systemd service:

```bash
sudo adduser SERVICE_USER msmtp-secrets
```

Create the secret directory and file with group access:

```bash
sudo install -d -o root -g msmtp-secrets -m 750 /etc/msmtp/secrets
sudo install -o root -g msmtp-secrets -m 640 /dev/null \
  /etc/msmtp/secrets/mailgun-password
sudoedit /etc/msmtp/secrets/mailgun-password
```

Reassert the permissions after editing:

```bash
sudo chown root:msmtp-secrets /etc/msmtp/secrets/mailgun-password
sudo chmod 640 /etc/msmtp/secrets/mailgun-password
```

Restart the affected service so its processes receive the new supplementary
group membership:

```bash
sudo systemctl restart SERVICE_NAME
```

For a systemd unit with an explicitly restricted group configuration, add the
group in a service override:

```bash
sudo systemctl edit SERVICE_NAME
```

Add:

```ini
[Service]
SupplementaryGroups=msmtp-secrets
```

Then reload systemd and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart SERVICE_NAME
```

## Deploy the non-secret configuration

After removing all inline credentials, install the repository configuration as
the system-wide msmtp configuration:

```bash
sudo install -o root -g root -m 644 \
  homelab-dns/msmtp/configs/msmtprc /etc/msmtprc
```

Mode `644` is appropriate only when `/etc/msmtprc` no longer contains secrets.
The file still exposes SMTP usernames, hostnames, sender addresses, and secret
file locations, but not the password itself.

If the system configuration contains other sensitive values, retain stricter
permissions and ensure every invoking user can read the configuration through
a narrowly scoped group.

## Verify permissions

Inspect every path component without printing the secret:

```bash
namei -l /etc/msmtp/secrets/mailgun-password
```

For a non-root service, verify that its effective account can read the file:

```bash
sudo -u SERVICE_USER test -r /etc/msmtp/secrets/mailgun-password \
  && echo "secret is readable" \
  || echo "secret is not readable"
```

Check the service's group membership:

```bash
id SERVICE_USER
```

Do not verify access by printing the file contents to the terminal.

## Test msmtp

First check that msmtp can parse the account configuration:

```bash
msmtp --pretend --account=mailgun recipient@example.com </dev/null
```

Run the same check as the service account when applicable:

```bash
sudo -u SERVICE_USER msmtp --pretend --account=mailgun \
  recipient@example.com </dev/null
```

Send a controlled test message:

```bash
printf 'Subject: msmtp secret test\n\nPassword evaluation succeeded.\n' \
  | sudo -u SERVICE_USER msmtp --account=mailgun recipient@example.com
```

When msmtp is intentionally run as root, omit `sudo -u SERVICE_USER`.

Use debug output only during troubleshooting and handle it as potentially
sensitive:

```bash
sudo -u SERVICE_USER msmtp --debug --account=mailgun \
  recipient@example.com </dev/null
```

Do not publish debug logs without reviewing and redacting them.

## Credential rotation

If a password has ever been committed to Git, copied into an issue, or exposed
in logs, treat it as compromised. Removing it from the current file does not
remove it from Git history.

Use this rotation sequence:

1. Create or obtain a new SMTP credential from the provider.
2. Put the new value in `/etc/msmtp/secrets/mailgun-password` with `sudoedit`.
3. Reapply the expected ownership and permissions.
4. Send a controlled test message.
5. Revoke the old credential after the test succeeds.
6. Coordinate any Git-history rewrite with all repository users if history
   must be scrubbed. A history rewrite affects existing clones and branches.

Never add `/etc/msmtp/secrets` or a copy of it to the repository. Back up
secrets only through an approved encrypted secret-management system.

## Troubleshooting

### `passwordeval` returned no output

Confirm that the secret file exists, contains the current password, and is
readable by the user running msmtp:

```bash
sudo -u SERVICE_USER test -s /etc/msmtp/secrets/mailgun-password
sudo -u SERVICE_USER test -r /etc/msmtp/secrets/mailgun-password
```

Both commands should exit successfully. The `-s` test also checks that the
file is not empty.

### Permission denied

Check all directory and file permissions with `namei -l`. The service user
needs execute permission on `/etc/msmtp/secrets` and read permission on the
secret file. Restart services after changing group membership.

### The wrong account is being used

Select the account explicitly:

```bash
msmtp --account=mailgun recipient@example.com
```

The `account default:` directive controls which account is used when no
account is selected. An aliases file changes recipient addresses; it does not
select an msmtp account.

### Configuration works as root but not as a service

Determine the service's actual execution identity:

```bash
systemctl show SERVICE_NAME -p User -p Group -p SupplementaryGroups
```

Then grant only that identity access using the `msmtp-secrets` group. Also
review the service's systemd sandbox settings if it has access to the secret
file by permission but still cannot open it.
