# Stage 1 — rebrand and visible outputs

The build overlay changes static/runtime branding without editing vendor files.
PlanetIR/ISIS adapters publish artifacts through OpenWebUI's upload handler, so
storage bytes and the Files database row are created together.

```bash
cd sacai-platform
cp .env.example .env
# Set PROJECT_NAME and secrets in .env, then:
./scripts/rebuild_offline.sh
```

Open the page before login and after login; check title, splash, favicon,
notifications, and PWA name. Complete one job, open Files, download its report,
and verify another user cannot access its URL.

