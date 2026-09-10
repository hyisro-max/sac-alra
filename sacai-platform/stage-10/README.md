# Stage 10 — grounding and verification

Install `../openwebui_functions/grounding_guard.py` as a Filter and enable it on
scientific models. Configure its audit URL/token. Run the offline pytest image
for deterministic math, schemas, and number matching.

Ask a test model to state a number absent from tool output. The Filter must append
a visible warning. Ask it to repeat an exact returned number; that number must
pass. Fetch the correlation audit and confirm submission, raw JSON, publication,
final text, matched/unmatched values are linked.

