# Stage 7 — admin cleanup

Install `../openwebui_tools/admin_cleanup.py` only for an admin test model. Call
`preview` with an age. Inspect every path and OpenWebUI file ID. Only after an
admin explicitly approves that exact list, call `execute` with the returned
unexpired token.

Verify a normal user is refused, changed/expired/reused tokens are refused,
targets outside output/tool-version roots are impossible, Files rows disappear
through the normal delete route, and audit events name actor/time/target.

