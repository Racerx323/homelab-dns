# Homelab DNS: High-Availability DNS with Pi-Hole, Unbound, and Keepalived

This repository contains configuration files and guidance for setting up a resilient, private, and ad-blocking DNS solution for your homelab. It combines [Pi-Hole](https://pi-hole.net/), [Unbound](https://unbound.net/), and [Keepalived](https://www.keepalived.org/) to provide a high-availability (HA) DNS service.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Overview

The goal of this setup is to create a robust DNS infrastructure that is a cornerstone of a reliable homelab network. A DNS outage can bring down nearly every service, so high availability is critical.

- **Pi-Hole**: Acts as the primary DNS server for your network clients. It provides network-wide ad-blocking and allows for local DNS record management.
- **Unbound**: Serves as a recursive, caching DNS resolver. Instead of forwarding queries to a public DNS provider (like Google or Cloudflare), Pi-Hole forwards queries to your local Unbound instance. Unbound then resolves the queries by communicating directly with the internet's root DNS servers, enhancing both privacy and performance.
- **Keepalived**: Provides high availability by managing a virtual IP (VIP) address. This VIP floats between two DNS servers. If the primary server goes down, Keepalived automatically assigns the VIP to the backup server, ensuring seamless DNS resolution for your clients with no manual intervention.

## Features

- **High Availability**: No more DNS-related downtime if one of your servers needs a reboot or fails.
- **Network-Wide Ad & Tracker Blocking**: Protect all devices on your network without any client-side software.
- **Enhanced Privacy**: Your DNS queries are not sent to a third-party provider. Unbound resolves them directly.
- **Improved Performance**: Common DNS queries are cached by Unbound, leading to faster response times.
- **Local DNS Management**: Easily define custom DNS records for your local services (e.g., `nas.local`, `proxmox.local`).

## Architecture

This setup assumes two identical nodes (physical or virtual) for redundancy. Each node runs Pi-Hole, Unbound, and Keepalived.

```text
                      +--------------------------------+
                      |      Your Router / Gateway     |
                      | (DHCP points DNS to Virtual IP)|
                      +---------------+----------------+
                                      |
                                      v
                            [ YOUR_VIRTUAL_IP ]
                        (Managed by Keepalived)
                                      |
                  /-------------------------------------\
                 |                                     |
      +----------+----------+ (MASTER)      +----------+----------+ (BACKUP)
      |       Node 1        |               |       Node 2        |
      |---------------------|               |---------------------|
      |  - Keepalived       | <--(VRRP)-->   |  - Keepalived       |
      |  - Pi-Hole          |               |  - Pi-Hole          |
      |  - Unbound          |               |  - Unbound          |
      +---------------------+               +---------------------+
                 |                                     |
                 | (Pi-Hole forwards to 127.0.0.1#5335) |
                 |                                     |
                 \------------------+------------------/
                                    |
                                    v
                             (Unbound resolves)
                                    |
                                    v
                         +--------------------+
                         | Internet Root &    |
                         | Authoritative DNS  |
                         +--------------------+
```

## Prerequisites

1. **Two Servers**: Two instances of a Linux distribution (e.g., Debian, Ubuntu, Raspberry Pi OS). These can be physical machines (like Raspberry Pis) or VMs.
2. **Static IPs**: Each server must have a static IP address configured.
3. **Virtual IP**: A free IP address on your network to be used as the Virtual IP (VIP). This IP should be in the same subnet as the two servers.

## Setup Guide

*This guide assumes you will store your configuration files in this repository. You should create directories like `unbound/` and `keepalived/` to hold the respective configuration files.*

1. **Clone Repository**: Clone this repository to a local machine to manage your configurations.

    ```sh
    git clone https://github.com/your-username/homelab-dns.git
    cd homelab-dns
    ```

2. **Install Software**: On **both** servers, install the necessary packages.

    ```sh
    # For Debian/Ubuntu based systems
    sudo apt update && sudo apt install -y pihole unbound keepalived
    ```

    *Note: Follow the on-screen instructions for the Pi-Hole installation.*

3. **Configure Unbound**:
    - Copy your Unbound configuration file (e.g., from `unbound/pi-hole.conf` in this repo) to `/etc/unbound/unbound.conf.d/pi-hole.conf` on both servers.
    - Restart Unbound to apply the changes:

        ```sh
        sudo systemctl restart unbound
        ```

4. **Configure Pi-Hole**:
    - In the Pi-Hole admin interface (`http://<pihole_ip>/admin`), go to **Settings -> DNS**.
    - Uncheck all public upstream DNS providers.
    - In the "Upstream DNS Servers" section, add `127.0.0.1#5335` as the **Custom 1 (IPv4)** upstream. This points Pi-Hole to your local Unbound instance.
    - Click "Save". Do this on both Pi-Hole instances.

5. **Configure Keepalived**:
    - You will need two versions of `keepalived.conf`, one for the master and one for the backup.
    - Customize your configuration files, replacing placeholders like `[INTERFACE]`, `[ROUTER_ID]`, `[PRIORITY]`, `[AUTH_PASS]`, and `[VIRTUAL_IP]`. The master should have a higher priority (e.g., 101) than the backup (e.g., 100).
    - Copy the appropriate `keepalived.conf` to `/etc/keepalived/keepalived.conf` on each server.
    - Restart Keepalived on both nodes:

        ```sh
        sudo systemctl restart keepalived
        ```

6. **Update Network DHCP**:
    - In your router's DHCP settings, change the primary (and only) DNS server to the **Virtual IP** (`[VIRTUAL_IP]`).
    - Renew the DHCP lease on your client devices to get the new DNS server settings.

## Verification

- **Check VIP**: On the master node, run `ip a` and verify that the virtual IP is attached to your network interface.
- **Test DNS**: From a client machine, use `nslookup` or `dig` to query a domain (e.g., `nslookup google.com`). It should resolve correctly.
- **Test Failover**:
    1. Start a continuous ping to an external domain from a client (e.g., `ping 1.1.1.1`).
    2. Shut down the master DNS node (`sudo shutdown now`).
    3. You should see a few dropped packets, but the ping should resume within seconds as the backup node takes over.
    4. Run `ip a` on the backup node; it should now have the virtual IP.

## License

This project is licensed under the GNU General Public License v3.0. See the LICENSE.md file for details.
