# Stage 14 — allowlisted remote Jupyter runtime

This optional stage runs existing Python notebooks on a standard Jupyter Server
without giving chat users arbitrary Python or notebook-path access. It adds the
single `jupyter_runtime` Tool and the `notebook-worker` service. The runtime
machine itself is external to this Compose stack.

## Prepare the Jupyter runtime

1. Confirm the address opens a Jupyter Server or JupyterLab deployment and that
   its REST API is enabled. JupyterHub user servers normally require a base URL
   such as `https://host/user/account`, not merely the hub landing page.
2. Obtain a dedicated API token with access only to the intended notebooks.
3. In each approved notebook, read the injected Python variable `product_id`
   (the identical alias `sacai_product_id` is also supplied). Do not prompt for
   a product ID interactively; stdin is disabled.
4. Ensure the notebook kernelspec exists on that server. The default Tool Valve
   is `python3`.

## Install and configure the Tool

In OpenWebUI, create one Tool from
`openwebui_tools/jupyter_runtime.py`. Configure these admin Valves:

```text
jupyter_server_url = http(s)://the-runtime-base-address
jupyter_server_token = the dedicated API token
kernel_name = python3
allowed_notebooks = {"tmc_stats":"notebooks/tmc_stats.ipynb"}
service_url = http://sacai-api:8000
service_token = the exact SACAI_INTERNAL_TOKEN from .env
artifact_root = /data/outputs
```

`allowed_notebooks` is the security boundary. Its keys are the only code names
users can choose; its values are relative paths already present on Jupyter.
Never add a general-purpose notebook that executes a string, shell command, or
user-supplied path.

## Acceptance sequence

1. Ask the Tool to `list`; verify only friendly code names are returned.
2. Ask it to `check`; verify the Jupyter version is returned without a token.
3. Submit one known `product_id` and code name. Record the returned job ID.
4. Poll `status` until success. Confirm the executed notebook, result JSON, and
   any PNG cell outputs appear in OpenWebUI Files.
5. Submit a slow test notebook and call `cancel`; confirm status remains
   cancelled and the remote Jupyter session disappears.
6. Try an unknown code name and confirm rejection occurs before any job starts.

The worker supports the standard Jupyter Contents, Sessions, Kernels, and
kernel-channel WebSocket APIs. If `check` works but submission fails before the
first cell, confirm that WebSockets are allowed by any reverse proxy. Use HTTPS
with certificate verification whenever traffic crosses an untrusted network.
