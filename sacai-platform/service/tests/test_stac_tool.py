"""Schema-aware parsing tests for the single general STAC Tool."""

import asyncio
import importlib.util
from pathlib import Path


def _tool():
    """Load the standalone STAC source and return a configured Tool instance."""

    path = Path(__file__).parents[2] / "openwebui_tools/stac_catalog.py"
    spec = importlib.util.spec_from_file_location("stac_catalog", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module.Tools()


def test_natural_query_maps_collection_date_bbox_and_arbitrary_fields(monkeypatch) -> None:
    """Map a loose combined query only through fields observed in the catalog."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "mars-ir"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": [collection_id or "mars-ir"],
            "observed_item_properties": {"eo:cloud_cover": ["float"], "instrument": ["str"]},
        },
    )
    monkeypatch.setattr(
        tool,
        "_json",
        lambda path, payload=None: {
            "features": [{"id": "item-1", "collection": "mars-ir", "properties": {"datetime": "2025-01-15"}}]
        },
    )
    result = asyncio.run(
        tool.stac_catalog(
            "Find products in mars-ir where cloud cover < 10 and instrument=TIR "
            "between 2025-01-01 and 2025-02-01 bbox [1,2,3,4]"
        )
    )
    assert result["status"] == "ok"
    assert result["search_parameters"]["collections"] == ["mars-ir"]
    assert result["search_parameters"]["datetime"] == "2025-01-01/2025-02-01"
    assert result["search_parameters"]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert result["search_parameters"]["query"]["eo:cloud_cover"] == {"lt": 10}
    assert result["search_parameters"]["query"]["instrument"] == {"eq": "TIR"}


def test_unsupported_field_is_explicit(monkeypatch) -> None:
    """Return a diagnostic rather than silently searching an invented field."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "mars-ir"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": ["mars-ir"],
            "observed_item_properties": {"instrument": ["str"]},
        },
    )
    result = asyncio.run(tool.stac_catalog("Find mars-ir where imaginary score > 2"))
    assert result["status"] == "unsupported_fields"
    assert result["unsupported_fields"] == ["imaginary score"]


def test_returns_sun_incidence_values_for_named_product_ids(monkeypatch) -> None:
    """Project exact values per requested ID and identify a missing property."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "lunar-products"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": ["lunar-products"],
            "observed_item_properties": {"datetime": ["str"], "view:incidence_angle": ["float"]},
            "observed_item_values": {},
        },
    )
    payloads = []

    def search(path, payload=None):
        payloads.append(payload)
        return {
            "numberMatched": 2,
            "features": [
                {
                    "id": "TMC-001",
                    "collection": "lunar-products",
                    "properties": {"datetime": "2020-01-01T00:00:00Z", "view:incidence_angle": 31.25},
                },
                {
                    "id": "TMC-002",
                    "collection": "lunar-products",
                    "properties": {"datetime": "2020-01-02T00:00:00Z"},
                },
            ],
        }

    monkeypatch.setattr(tool, "_json", search)
    result = asyncio.run(
        tool.stac_catalog("Give me all the valuese for sun incidence for these product IDs TMC-001, TMC-002")
    )

    assert payloads[-1]["ids"] == ["TMC-001", "TMC-002"]
    assert "query" not in payloads[-1]
    assert result["requested_fields"] == [{"requested": "sun incidence", "resolved": "view:incidence_angle"}]
    assert result["values_by_product"][0]["values"]["view:incidence_angle"] == 31.25
    assert result["values_by_product"][1]["missing_fields"] == ["view:incidence_angle"]
    assert result["missing_values"] == [{"product_id": "TMC-002", "field": "view:incidence_angle"}]
    assert result["not_found_product_ids"] == []


def test_bare_year_and_tmc_collection_are_resolved_without_guessing(monkeypatch) -> None:
    """Turn a catalog-backed TMC label and bare year into exact STAC filters."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "lunar-tmc", "title": "Terrain Mapping Camera"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": [collection_id],
            "observed_item_properties": {"view:incidence_angle": ["float"]},
            "observed_item_values": {},
        },
    )
    payloads = []

    def search(path, payload=None):
        payloads.append(payload)
        return {"features": []}

    monkeypatch.setattr(tool, "_json", search)
    result = asyncio.run(tool.stac_catalog("Sun incidence values for products from 2020 TMC"))

    assert result["status"] == "ok"
    assert payloads[-1]["collections"] == ["lunar-tmc"]
    assert payloads[-1]["datetime"] == "2020-01-01T00:00:00Z/2020-12-31T23:59:59Z"


def test_observed_sensor_term_and_pagination_are_reported(monkeypatch) -> None:
    """Use observed TMC metadata and continue through a STAC next link."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "lunar-products"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": ["lunar-products"],
            "observed_item_properties": {"platform": ["str"], "view:incidence_angle": ["float"]},
            "observed_item_values": {"platform": ["TMC"]},
        },
    )
    calls = []

    def search(path, payload=None):
        calls.append((path, payload))
        if path == "/search":
            return {
                "numberMatched": 2,
                "features": [
                    {
                        "id": "one",
                        "collection": "lunar-products",
                        "properties": {"platform": "TMC", "view:incidence_angle": 10.0},
                    }
                ],
                "links": [{"rel": "next", "href": "http://stac.test/page-2"}],
            }
        return {
            "features": [
                {
                    "id": "two",
                    "collection": "lunar-products",
                    "properties": {"platform": "TMC", "view:incidence_angle": 20.0},
                }
            ]
        }

    monkeypatch.setattr(tool, "_json", search)
    result = asyncio.run(tool.stac_catalog("Give sun incidence values for products from 2020 TMC", limit=10))

    assert calls[0][1]["query"]["platform"] == {"eq": "TMC"}
    assert calls[1][0] == "http://stac.test/page-2"
    assert result["returned"] == 2
    assert result["truncated"] is False
    assert result["distinct_values"]["view:incidence_angle"] == [10.0, 20.0]


def test_cap_does_not_misreport_unfetched_ids_as_not_found(monkeypatch) -> None:
    """Distinguish unresolved IDs behind a cap from IDs proven absent."""

    tool = _tool()
    monkeypatch.setattr(tool, "_collections", lambda: [{"id": "lunar-products"}])
    monkeypatch.setattr(
        tool,
        "_schema",
        lambda collection_id="", product_ids=None: {
            "collection_ids": ["lunar-products"],
            "observed_item_properties": {"view:incidence_angle": ["float"]},
            "observed_item_values": {},
        },
    )
    monkeypatch.setattr(
        tool,
        "_json",
        lambda path, payload=None: {
            "numberMatched": 2,
            "features": [
                {
                    "id": "TMC-001",
                    "collection": "lunar-products",
                    "properties": {"view:incidence_angle": 31.25},
                }
            ],
            "links": [{"rel": "next", "href": "http://stac.test/page-2"}],
        },
    )
    result = asyncio.run(
        tool.stac_catalog(
            "Give sun incidence values for product IDs TMC-001, TMC-002",
            limit=1,
        )
    )

    assert result["truncated"] is True
    assert result["not_found_product_ids"] == []
    assert result["unresolved_product_ids"] == ["TMC-002"]
