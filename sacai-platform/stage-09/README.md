# Stage 9 — model and prompt governance

Follow `../docs/MODEL_EVALUATION.md`. Run the checked-in cases against current
and candidate models on a connected staging host, then repeat after full offline
transfer. Do not swap models from public ranking alone.

Edit prompts only in `../prompts/`, append the change to `BUILD_LOG.md`, then
copy the full text into Workspace → Models → edit → System Prompt. Reopen it,
start a fresh chat, and rerun tool/grounding tests.

