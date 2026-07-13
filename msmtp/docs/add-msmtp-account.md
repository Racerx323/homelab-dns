# Add a password-authenticated msmtp account

This guide describes how to use `add-msmtp-account.sh` on Debian 12. The
script creates a password-authenticated SMTP account without placing the
password in `/etc/msmtprc`.

The script follows these rules:

- If `/etc/msmtprc` exists, the new account is appended without changing
  existing accounts or the current default account.
- If `/etc/msmtprc` does not exist, a complete system configuration is
  created and the new account becomes the default.
- Duplicate account names are rejected.
- The password is stored separately and referenced with `passwordeval`.
- Passwords are accepted only through a hidden `/dev/tty` prompt.
- SMTP authentication must use STARTTLS or implicit TLS.
- Configuration replacement and secret replacement use temporary files on
  the same filesystem.

## Prerequisites

Install msmtp and the Debian certificate bundle:

```bash
sudo apt-get update
sudo apt-get install msmtp msmtp-mta ca-certificates
```

Copy or clone the repository onto the Debian 12 host. Ensure that the script
is executable:

```bash
chmod 755 homelab-dns/msmtp/scripts/add-msmtp-account.sh
```

## Interactive setup

Run the script without account options to answer each prompt:

```bash
sudo ./homelab-dns/msmtp/scripts/add-msmtp-account.sh
```

The script prompts for:

1. A unique msmtp account name.
2. The SMTP server hostname or address.
3. The TLS mode.
4. The SMTP port.
5. The envelope-from address.
6. The SMTP authentication username.
7. The password and confirmation.

When invoked with `sudo`, the calling user is authorized to read the secret
unless `--service-user` or `--root-only` selects a different access model.

## Flag-driven setup

Provide non-secret account details as options. The password is still prompted
for interactively and cannot be supplied on the command line:

```bash
sudo ./homelab-dns/msmtp/scripts/add-msmtp-account.sh \
  --account mailgun \
  --host smtp.mailgun.org \
  --port 587 \
  --from system@example.com \
  --username system@example.com \
  --tls-mode starttls \
  --service-user pi
```

Authorize multiple service accounts by repeating the option:

```bash
sudo ./homelab-dns/msmtp/scripts/add-msmtp-account.sh \
  --account monitoring \
  --host smtp.example.com \
  --from monitoring@example.com \
  --username monitoring@example.com \
  --service-user pi \
  --service-user prometheus
```

Use `--help` for the complete option list:

```bash
./homelab-dns/msmtp/scripts/add-msmtp-account.sh --help
```

## TLS modes

### STARTTLS

`starttls` begins with a normal SMTP connection and upgrades it to TLS before
authentication. Its default port is `587`:

```bash
--tls-mode starttls --port 587
```

The generated account contains:

```ini
auth on
tls on
tls_starttls on
```

### Implicit TLS

`implicit` establishes TLS immediately. Its default port is `465`:

```bash
--tls-mode implicit --port 465
```

The generated account contains:

```ini
auth on
tls on
tls_starttls off
```

The script intentionally does not support password authentication over a
cleartext connection.

## Existing configuration behavior

When `/etc/msmtprc` exists, its ownership and permissions are preserved. The
new block is appended:

```ini
# SMTP account: example
account example
host smtp.example.com
port 587
from system@example.com
user system@example.com
auth on
tls on
tls_starttls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
passwordeval "/usr/bin/cat /etc/msmtp/secrets/example-password"
```

The existing `account default:` declaration is not changed. Select the new
account explicitly with `--account=example`, or update the default manually
after testing.

## New configuration behavior

If `/etc/msmtprc` is absent, the script creates it with mode `644`, common TLS
defaults, the new account, and:

```ini
account default: example
```

The password is not stored in this file, so the configuration can be readable
without exposing the SMTP credential.

## Secret permissions

By default, the password is stored at:

```text
/etc/msmtp/secrets/ACCOUNT-password
```

The default group-based permissions are:

```text
drwxr-x--- root msmtp-secrets /etc/msmtp/secrets
-rw-r----- root msmtp-secrets ACCOUNT-password
```

Use `--service-user USER` to grant a service access. Group membership applies
after the user logs in again or the affected service restarts.

All members of `msmtp-secrets` can read all secrets stored under the default
directory. For account-specific isolation, create a dedicated group with
`--group` and use a separate `--secret-file` directory whose parent is not
shared with other account groups.

For root-only use:

```bash
sudo ./homelab-dns/msmtp/scripts/add-msmtp-account.sh \
  --account root-relay \
  --host smtp.example.com \
  --from root@example.com \
  --root-only
```

Root-only secrets use directory mode `700` and file mode `600`.

## Verification

Inspect the generated settings without sending mail:

```bash
msmtp --pretend --account=ACCOUNT recipient@example.com </dev/null
```

Inspect permissions without printing the password:

```bash
namei -l /etc/msmtp/secrets/ACCOUNT-password
test -r /etc/msmtp/secrets/ACCOUNT-password && echo readable
```

Send a controlled test:

```bash
printf 'Subject: msmtp account test\n\nThe new account works.\n' \
  | msmtp --account=ACCOUNT recipient@example.com
```

## Troubleshooting

### Account already exists

The script will not modify or replace an existing account. Choose a different
account name or edit the existing configuration deliberately.

### Permission denied while reading the password

Confirm that the invoking user belongs to the configured secret group:

```bash
id
namei -l /etc/msmtp/secrets/ACCOUNT-password
```

Log out and back in after adding an interactive user to the group. Restart a
systemd service after changing its service user's groups.

### Secret file already exists

The script requests confirmation before replacing a secret that already
exists. Declining leaves the file and configuration unchanged.

### Configuration exists but no default account is changed

This is intentional. Appending a new account must not silently redirect
existing system mail. Test the account explicitly before changing the default.

## Security notes

- Never add a password as a `password` directive in `msmtprc`.
- Never provide a password in a shell argument, environment variable, or
  redirected command that may be logged.
- Do not print or publish `msmtp --debug` output without reviewing it for
  sensitive authentication data.
- Rotate any credential that has previously been committed to Git, even if it
  was on a commented line.
- See `msmtp-secrets-configuration.md` for additional secret-management and
  credential-rotation guidance.
