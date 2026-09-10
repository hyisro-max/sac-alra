# Stage 2 — disconnected containers

Use `../docs/OFFLINE_DEPLOYMENT.md`; it is the complete beginner runbook.
When the connected machine is AlmaLinux, begin with
`../docs/ALMALINUX_CONNECTED_BUILDER.md` and the clean archive created on macOS.

```bash
cd sacai-platform
./scripts/verify_offline_bundle.sh
./scripts/load_offline_images.sh
./scripts/rebuild_offline.sh
docker compose ps
```

The stage passes only when build/start succeed with host egress disabled. A
missing artifact is fixed on the connected staging host, never by reconnecting
production.
