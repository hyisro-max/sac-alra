# Stage 11 — LangGraph orchestration

`../service/app/orchestrator.py` contains two checkpointed graphs: conditional
raw-product → ISIS (or skip) → PlanetIR → numeric grounding → report, and cleanup
preview → human interrupt → exact-token execution. SQLite checkpoints live on
the audit volume.

Install `../openwebui_tools/scientific_workflow.py`, configure its service
Valves, and enable it on a private test model. STAC remains the only catalog
interface; attach the selected/downloaded asset before submitting the workflow.

Test a GeoTIFF and raw product separately; inspect that only raw data enters the
ISIS node. Supply deliberately ungrounded final text and confirm the graph
interrupts. Resume with corrected text. For cleanup, confirm no execution is
possible before the matching preview-token resume.
