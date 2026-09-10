"""Search and describe access to the extracted ISIS3 application catalog.

Synchronous, no queue: this is an in-memory lookup against the static
365-entry catalog produced by extract_isis_catalog.py from ISIS's own XML
docs, not a scientific job. Mirrors the sync style of health/cleanup in
main.py rather than the Celery job pattern used for planetir/isis3/notebook.
"""

import json
from functools import lru_cache
from typing import Any

from .config import get_settings
from .schemas import CatalogEntry, CatalogSearchHit


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, dict[str, Any]]:
    """Load and index the ISIS catalog JSON once per process.

    There are no inputs; the path comes from Settings.isis_catalog_path.
    Returns a dict keyed by application name for O(1) describe() lookups.
    Cached: the catalog is static per image build, not re-read per request.
    """

    path = get_settings().isis_catalog_path
    if not path.is_file():
        raise RuntimeError(
            f"ISIS catalog not found at {path}. Set SACAI_ISIS_CATALOG_PATH or "
            "bake isis_catalog.json into the image at the configured default."
        )
    with path.open() as f:
        entries = json.load(f)
    return {entry["name"]: entry for entry in entries}


def search(query: str, limit: int = 15) -> list[CatalogSearchHit]:
    """Return ISIS applications whose name, brief, or category match query.

    A free-text query and result cap are inputs. Matches on the application
    name are ranked above brief/category matches. Intended to back a Tool's
    "which of these could do X" discovery step, not to execute anything.
    """

    catalog = _load_catalog()
    q = query.strip().lower()
    if not q:
        return []

    name_hits = []
    other_hits = []
    for entry in catalog.values():
        name = entry["name"].lower()
        brief = (entry.get("brief") or "").lower()
        categories = " ".join(entry.get("category") or []).lower()

        if q in name:
            name_hits.append(entry)
        elif q in brief or q in categories:
            other_hits.append(entry)

    ranked = name_hits + other_hits
    return [
        CatalogSearchHit(name=e["name"], brief=e.get("brief"), category=e.get("category") or [])
        for e in ranked[:limit]
    ]


def describe(name: str) -> CatalogEntry:
    """Return the full parameter schema for one named ISIS application.

    The exact application name (e.g. from a prior search() result) is the
    input. Raises KeyError if the name isn't in the catalog -- callers map
    this to a 404, matching the _metadata() pattern in main.py for jobs.
    """

    catalog = _load_catalog()
    if name not in catalog:
        raise KeyError(name)
    entry = catalog[name]
    return CatalogEntry(
        name=entry["name"],
        brief=entry.get("brief"),
        category=entry.get("category") or [],
        parameters=entry.get("parameters") or [],
    )
