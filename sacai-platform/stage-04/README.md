# Stage 4 — PlanetIR

Install `../openwebui_tools/planetir.py` and configure its internal URL/token.
Attach exactly one GeoTIFF and ask for analysis. Submit must return immediately
with a job ID; call status until succeeded.

Check metadata, all-band statistics, histogram arrays, noise/blur/striping
evidence, preview/histogram/report artifacts, and restore-mode GeoTIFF. Run the
known-answer tests with the disconnected test image described in Stage 2.

