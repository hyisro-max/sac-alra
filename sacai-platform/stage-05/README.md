# Stage 5 — optional ISIS3

First complete `../docs/ISIS3_OFFLINE.md`. Start the profile:

```bash
docker compose --profile isis up -d --pull never isis-worker
```

Install `../openwebui_tools/isis3_preprocess.py`. Test one raw mission product
and confirm the registered result is a calibrated, projected GeoTIFF accepted by
PlanetIR. Submit a ready GeoTIFF and confirm ISIS returns `skipped`.

