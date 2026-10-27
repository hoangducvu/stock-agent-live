Current architecture, AI/Slack setup, tests and deployment: see README.md.
The notes below describe the original deployment bundle.

Nexlara Oracle Linux 9 / ARM64 deployment

Prerequisites: podman and curl installed; loginctl enable-linger opc already run.
Extract this archive into a new directory in opc's home. Run bash install.sh as opc.
This bundle contains application source, the built React frontend, and pinned
Python dependency versions from the validated cloud development environment.
It contains no API keys, .env files, SSH keys, account state, or trading logs.

Two rootless Podman services start through Quadlet: nexlara-api and nexlara-web.
The backend can launch bot subprocesses on request; no standalone bot service
is started and no Alpaca credentials are supplied. BOT_SCRIPT points at main.py.
The app listens on 127.0.0.1:8080 only. It is not publicly exposed. Configure
HTTPS and access protection before making /api publicly available.

From Windows, use the existing SSH key to forward a local port:
ssh -i "D:\MSl\ssh-key-2026-10-23.key" -L 8080:127.0.0.1:8080 opc@158.101.164.228
Then open http://localhost:8080/ on that computer. Keep the SSH session open.
This Oracle deployment is separate from the cloud onboarding UI.

Diagnostics:
systemctl --user status nexlara-api.service nexlara-web.service --no-pager
journalctl --user -u nexlara-api.service -u nexlara-web.service -n 80 --no-pager
podman ps
bash check.sh

Stop services:
systemctl --user stop nexlara-web.service nexlara-api.service

Named volumes nexlara-data and nexlara-logs retain application state.
Do not delete them when updating the application. Services restart after
reboot through Quadlet and user lingering. Bots started through the UI are
not automatically resumed after backend restart. Persistent scheduling and
account-backed trading behavior still need separate validation.

Production frontend is prebuilt to avoid the missing nexlara/ directory in
the repository's original Dockerfile. Its build base is /tradingbot/; nginx
serves the existing React homepage at / and proxies /api internally.
Application source and dependency manifests have not been modified.
