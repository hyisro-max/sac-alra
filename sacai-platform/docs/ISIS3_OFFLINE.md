# ISIS3 offline and RHEL 9.5 guide

ISIS3 is optional and handles only raw PDS/IMG/ISIS ingestion, calibration,
SPICE geometry, and map projection. A calibrated, projected GeoTIFF must skip
ISIS and go directly to PlanetIR.

Upstream documentation does not establish native RHEL 9.5 compatibility. SACAI
therefore ships ISIS in a pinned AMD64 container and treats execution on the
actual RHEL 9.5 kernel as an acceptance test, not an assumption.

## Connected preparation

1. Build/pull the pinned image as `sacai/isis-runtime:8.3.0-amd64` on AMD64
   Linux and run `isisversion` inside it. Do this before
   `prepare_connected_bundle.sh`; that script detects the image, builds the
   worker, and saves both images in `offline/images/isis-runtime-amd64.tar`.
2. Set `ISISROOT` to the image's installation root (SACAI expects `/opt/isis`).
3. Build a complete `/opt/isisdata` outside the image. Fetch base data and every
   mission directory required by the ingest/calibration programs. Include SPICE
   kernels, leap-second/planet constants, DEMs, and calibration tables.
4. Configure the four command templates in `.env`: ingest, calibrate, SPICE, and
   project. The wrapper replaces only `{input}` and `{output}` and executes an
   argument list without a shell.
5. Run representative products from every mission. Verify output driver,
   dimensions, CRS, transform, nodata, and reference pixel statistics.
6. Freeze the image with `docker save`; checksum the image, ISISDATA files,
   command templates, ISIS version, and test results.

## Offline run

```bash
cd sacai-platform
./scripts/load_offline_images.sh
docker compose --profile isis up -d --pull never isis-worker
docker compose logs -f isis-worker
```

`ISISDATA` is mounted read-only. Job outputs use `/data/outputs`; raw uploads are
read-only. Missing mission data must fail the job explicitly. Never download
kernels at job time and never retry an already-calibrated GeoTIFF through ISIS.
