# HTTPS preparation

Private validation passed in the user's normal VM shell on 2026-10-23.
The website, assets, client routes and API responded, trading was inactive,
and loopback binding and boot configuration checks passed. Reboot behavior
and trading recovery remain untested.

Run the read-only diagnostics first:

```bash
cd ~/nexlara-deployment/nexlara-oracle
bash https/preflight.sh
```

Then stage the proxy without exposing it:

```bash
sudo bash https/stage.sh
```

Staging pulls the official ARM64-compatible Caddy image and pins its resolved
digest, generates a random login password, hashes it with Caddy, validates
the configuration without network access, and stores new files under
`/etc/nexlara-edge`. It refuses to overwrite an existing staging directory
or Quadlet. The agent could only check script syntax; image execution and
Caddy validation require the normal VM shell.

The proposed proxy runs as a rootful Podman Quadlet so it can bind ports
80/443 and reach the existing rootless application's loopback port. The
application containers and their volumes stay unchanged. The whole website,
including API routes, requires a separate HTTP Basic login over HTTPS.
The Caddy administration endpoint is disabled. Certificate state will be
retained under `/var/lib/nexlara-edge`. Its service restarts automatically.

Before activation, review the diagnostics for port conflicts and DNS records.
Confirm that the domain's A record points to this VM's reserved public IP
and that any AAAA record routes correctly. The bundle mentions
`158.101.164.228`, and the user has now confirmed this is the current VM
public IPv4. Cloudflare's current apex origin is `65.108.242.41`, which needs
to be replaced for this deployment. Preserve all email-related records.
Review the active host firewall zone and OCI subnet/NSG ingress for TCP
80/443. Preserve SSH rules and keep 8080 and 8000 private. OCI rules cannot
be verified from the current agent session.

Staging and runtime Caddy validation passed in the user's normal VM shell.
The preflight showed no port conflicts, an active public firewall zone on
enp0s6 with only SSH/DHCPv6 allowed, and Cloudflare-proxied domain addresses.
Public DNS does not reveal the configured Cloudflare origin IP. The public
HTTPS request timed out; this does not identify which network layer failed.

Activation is deferred until origin routing and OCI ingress are reviewed.
In OCI, add stateful ingress for TCP destination ports 80 and 443 from
`0.0.0.0/0` to the applicable instance NSG or subnet security list; preserve
SSH and other existing rules. In Cloudflare, change only the apex A record
to `158.101.164.228`. Temporarily set that record to DNS only while the origin
certificate is issued. Verify public DNS returns the new address before
activation. Once those checks are complete, run:

```bash
sudo bash https/activate.sh
sudo bash https/verify.sh
```

After these origin checks pass, set Cloudflare SSL/TLS encryption to Full
(strict), then restore the apex record's Proxied setting. Re-run the HTTPS
verifier to check both direct-origin and Cloudflare paths. Review other
proxied hosts before changing a zone-wide SSL mode; use a hostname-specific
configuration rule if they need a different setting. Certificate issuance
can take time; if verification initially fails, inspect
`sudo journalctl -u nexlara-edge -n 60 --no-pager` and retry verification
after issuance succeeds. Do not repeatedly restart the service.

Activation creates persistent Caddy directories, installs the staged Quadlet
under `/etc/containers/systemd`, reloads systemd and starts the gateway. It
adds only HTTP/HTTPS to the confirmed public host firewall zone, both runtime
and permanent, preserving SSH rules without reloading the firewall.
DNS and OCI rules remain unchanged. Do not use `systemctl enable` for a generated Quadlet;
its `[Install]` section supplies boot linkage. Caddy then obtains and renews
the certificate automatically when domain routing and ingress permit it.

The verifier checks trusted TLS for the direct origin and public domain
without printing login credentials or submitting orders.
After activation, verify that HTTP redirects to HTTPS, unauthenticated API
requests receive 401, and authenticated website/API requests succeed with
normal certificate verification. Confirm trading is still inactive. Use a
password prompt rather than placing credentials in command arguments or
chat. A server reboot test should be scheduled separately.

This proxy protects public access; it does not implement trading-process
recovery or repair the strategy and log-handling defects documented in
`deployment-review/STATUS.md`. Unattended trading remains disabled pending
those application changes and tests.

References: [Caddy basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth),
[automatic HTTPS](https://caddyserver.com/docs/automatic-https), and
[Podman Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html).
