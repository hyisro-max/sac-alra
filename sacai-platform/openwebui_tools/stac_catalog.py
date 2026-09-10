"""
title: SACAI STAC Catalog
description: Inspect and search one configurable STAC API without inventing catalog fields.
author: SACAI
version: 1.1.0
"""

import asyncio
import json
import re
import ssl
from datetime import datetime
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class Tools:
    """Expose one general schema-aware STAC entry point to the model."""

    class Valves(BaseModel):
        """Configure the only STAC server connection used by SACAI Tools."""

        stac_url: str = Field(
            default="http://10.61.247.35:3000",
            description="Base URL of the self-hosted STAC API; editable without changing Tool code.",
        )
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        verify_tls: bool = Field(default=True, description="Verify TLS certificates for HTTPS STAC servers.")
        schema_sample_items: int = Field(default=20, ge=1, le=100)
        server_page_limit: int = Field(default=100, ge=1, le=1000)
        field_aliases: dict[str, str] = Field(
            default_factory=lambda: {
                "sensor": "platform",
                "cloud cover": "eo:cloud_cover",
                "sun incidence": "view:incidence_angle",
                "sun incidence angle": "view:incidence_angle",
                "incidence angle": "view:incidence_angle",
            },
            description="Natural-language alias to actual STAC property name. Update after schema inspection.",
        )

    class UserValves(BaseModel):
        """Cap how many catalog records an individual user receives per call."""

        max_results: int = Field(default=50, ge=1, le=500)

    def __init__(self):
        """Initialize default STAC Valves before OpenWebUI applies stored values."""

        self.valves = self.Valves()

    def _json(self, path_or_url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Request and decode one JSON document from the configured STAC API.

        A relative/absolute URL and optional POST payload are inputs. The output
        is a decoded object; HTTP errors retain the server's detail text.
        """

        base = self.valves.stac_url.rstrip("/") + "/"
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else urljoin(base, path_or_url.lstrip("/"))
        context = None
        if url.startswith("https://") and not self.valves.verify_tls:
            context = ssl._create_unverified_context()
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            method="POST" if payload is not None else "GET",
            headers={"Accept": "application/geo+json, application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"STAC server returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"STAC server is unavailable: {error.reason}") from error

    @staticmethod
    def _links(document: dict[str, Any], relation: str) -> list[str]:
        """Return link hrefs with one STAC relation from a JSON document.

        The document and relation are inputs. The URL list supports pagination
        without assuming a server-specific route structure.
        """

        return [
            str(link["href"])
            for link in document.get("links", [])
            if isinstance(link, dict) and link.get("rel") == relation and link.get("href")
        ]

    def _collections(self) -> list[dict[str, Any]]:
        """Fetch all paginated collection records from the configured server.

        There are no inputs. The returned collection list is used by listing,
        schema discovery, and collection-name validation.
        """

        if self.valves.verify_tls:
            try:
                from pystac_client import Client

                client = Client.open(
                    self.valves.stac_url,
                    timeout=self.valves.request_timeout_seconds,
                )
                return [collection.to_dict() for collection in client.get_collections()]
            except Exception:
                # Some internal servers omit advertised conformance classes.
                # The standards-level endpoint fallback still paginates safely.
                pass
        document = self._json("/collections")
        collections = list(document.get("collections", []))
        seen = set()
        while self._links(document, "next"):
            url = self._links(document, "next")[0]
            if url in seen:
                break
            seen.add(url)
            document = self._json(url)
            collections.extend(document.get("collections", []))
        return collections

    def _schema(self, collection_id: str = "", product_ids: list[str] | None = None) -> dict[str, Any]:
        """Discover actual item properties from collection metadata and samples.

        The optional collection ID is the input. The returned schema summary
        names observed properties and types, preventing unsupported-field
        searches from silently returning misleading empty results.
        """

        properties: dict[str, set[str]] = {}
        observed_values: dict[str, list[str | int | float | bool]] = {}

        def remember(key: str, value: Any) -> None:
            """Remember bounded scalar examples without changing their value."""

            if value is None or isinstance(value, (dict, list)):
                return
            values = observed_values.setdefault(str(key), [])
            if value not in values and len(values) < self.valves.schema_sample_items:
                values.append(value)
        collections = self._collections()
        selected = [entry for entry in collections if not collection_id or entry.get("id") == collection_id]
        if collection_id and not selected:
            raise ValueError(f"Collection '{collection_id}' does not exist.")
        for collection in selected:
            summaries = collection.get("summaries", {})
            if isinstance(summaries, dict):
                for key, values in summaries.items():
                    examples = values if isinstance(values, list) else [values]
                    for value in examples:
                        properties.setdefault(str(key), set()).add(type(value).__name__)
                        remember(str(key), value)
        payload: dict[str, Any] = {"limit": self.valves.schema_sample_items}
        if collection_id:
            payload["collections"] = [collection_id]
        if product_ids:
            payload["ids"] = product_ids[: self.valves.schema_sample_items]
        sample = self._json("/search", payload)
        for feature in sample.get("features", []):
            for key, value in (feature.get("properties") or {}).items():
                properties.setdefault(str(key), set()).add(type(value).__name__)
                remember(str(key), value)
        return {
            "collection_ids": [entry.get("id") for entry in selected],
            "observed_item_properties": {key: sorted(values) for key, values in sorted(properties.items())},
            "observed_item_values": {key: values for key, values in sorted(observed_values.items())},
            "note": "Observed from collection summaries and sampled items; sparse properties may require a larger sample.",
        }

    @staticmethod
    def _operation(query: str, requested: str) -> str:
        """Infer a conservative operation when the caller leaves it automatic.

        Query text and requested operation are inputs. The output never infers
        a destructive action; it selects only collection/item/schema/search.
        """

        if requested != "auto":
            return requested
        lowered = query.lower()
        if "schema" in lowered or "field" in lowered and "available" in lowered:
            return "schema"
        if re.search(r"\bvalues?e?\b", lowered):
            return "search"
        if "collection" in lowered and any(word in lowered for word in ("list", "show", "available")):
            return "list_collections"
        if any(word in lowered for word in ("list products", "list items", "show products", "show items")):
            return "list_items"
        return "search"

    def _resolve_field(self, phrase: str, available: set[str]) -> str | None:
        """Map one natural-language field phrase to an observed STAC property.

        The phrase and observed property set are inputs. An exact/alias match is
        returned, or None so the Tool can explicitly report unsupported fields.
        """

        normalized = phrase.strip().lower().replace("_", " ")
        direct = {field.lower().replace("_", " "): field for field in available}
        if normalized in direct:
            return direct[normalized]
        alias = self.valves.field_aliases.get(normalized)
        if alias in available:
            return alias
        suffix_matches = [field for field in available if field.lower().split(":")[-1].replace("_", " ") == normalized]
        return suffix_matches[0] if len(suffix_matches) == 1 else None

    def _infer_collection(self, query: str) -> str:
        """Infer one exact collection ID mentioned in natural-language text.

        Query text is the input. The output is an exact catalog collection ID,
        an empty string when none is named, or an ambiguity error for multiples.
        """

        lowered = query.lower()
        generic = {"collection", "data", "dataset", "image", "images", "item", "product", "products"}
        matches: list[str] = []
        for collection in self._collections():
            collection_id = str(collection.get("id") or "")
            if not collection_id:
                continue
            title = str(collection.get("title") or "")
            labels = {collection_id.lower()}
            labels.update(
                token
                for token in re.split(r"[^a-z0-9]+", collection_id.lower())
                if len(token) >= 3 and token not in generic
            )
            if title:
                labels.add(title.lower())
                title_words = re.findall(r"[A-Za-z0-9]+", title)
                if len(title_words) >= 2:
                    labels.add("".join(word[0] for word in title_words).lower())
            if any(re.search(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])", lowered) for label in labels):
                matches.append(collection_id)
        matches = list(dict.fromkeys(matches))
        if len(matches) > 1:
            raise ValueError(f"Query names multiple collections; choose one explicitly: {matches}")
        return matches[0] if matches else ""

    @staticmethod
    def _product_ids(query: str, explicit_ids: list[str] | None = None) -> list[str]:
        """Return explicit or plainly labelled STAC product/item IDs."""

        if explicit_ids:
            return list(dict.fromkeys(str(value).strip() for value in explicit_ids if str(value).strip()))
        match = re.search(
            r"\b(?:these\s+)?(?:product|item)\s+ids?\s*(?:are|is|:|=)?\s*(.+?)(?=\s+\b(?:from|in|where|with|between|before|after|bbox|bounding)\b|$)",
            query,
            re.I,
        )
        if not match:
            return []
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]*", match.group(1))
        ignored = {"and", "or", "the", "products", "product", "items", "item"}
        return list(dict.fromkeys(token for token in tokens if token.lower() not in ignored))

    def _requested_fields(
        self,
        query: str,
        available: set[str],
        explicit_fields: list[str] | None = None,
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        """Resolve requested value/projection fields against the observed schema."""

        phrases: list[str] = [str(value).strip() for value in explicit_fields or [] if str(value).strip()]
        if not phrases and re.search(r"\bvalues?e?\b", query, re.I):
            candidates = set(self.valves.field_aliases)
            for field in available:
                candidates.add(field.lower().replace("_", " "))
                candidates.add(field.lower().split(":")[-1].replace("_", " "))
            phrases.extend(
                candidate
                for candidate in sorted(candidates, key=len, reverse=True)
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])", query, re.I)
            )
            if not phrases:
                match = re.search(
                    r"\bvalues?e?\s+(?:for|of)\s+(?:the\s+)?(.+?)(?=\s+\b(?:for|from|in|where|with)\b|$)",
                    query,
                    re.I,
                )
                if match:
                    phrases.append(match.group(1).strip())

        resolved: list[str] = []
        unsupported: list[str] = []
        mappings: list[dict[str, str]] = []
        for phrase in phrases:
            field = self._resolve_field(phrase, available)
            if not field:
                unsupported.append(phrase)
                continue
            if field not in resolved:
                resolved.append(field)
                mappings.append({"requested": phrase, "resolved": field})
        return resolved, sorted(set(unsupported)), mappings

    @staticmethod
    def _observed_term_filters(query: str, schema: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Match free terms only to unique scalar values observed in the catalog."""

        ignored = {
            "and", "all", "from", "give", "item", "items", "product", "products", "show", "the", "value", "values", "valuese"
        }
        hits: dict[str, list[tuple[str, Any]]] = {}
        for field, values in schema.get("observed_item_values", {}).items():
            for value in values:
                text = str(value).strip()
                lowered = text.lower()
                if (
                    len(text) < 3
                    or len(text) > 64
                    or lowered in ignored
                    or not re.search(r"[A-Za-z]", text)
                    or re.fullmatch(r"\d{4}(?:-\d{2}-\d{2}.*)?", text)
                ):
                    continue
                if re.search(rf"(?<![A-Za-z0-9_:\-]){re.escape(text)}(?![A-Za-z0-9_:\-])", query, re.I):
                    hits.setdefault(lowered, []).append((str(field), value))

        filters: dict[str, dict[str, Any]] = {}
        inferred: list[dict[str, Any]] = []
        for text, matches in hits.items():
            unique = list(dict.fromkeys((field, json.dumps(value, sort_keys=True)) for field, value in matches))
            fields = sorted({field for field, _ in unique})
            if len(fields) > 1:
                raise ValueError(f"Catalog term '{text}' is ambiguous across observed fields: {fields}")
            field, value = matches[0]
            filters[field] = {"eq": value}
            inferred.append({"term": text, "field": field, "value": value})
        return filters, inferred

    @staticmethod
    def _typed(value: str) -> str | int | float | bool:
        """Convert a query literal to a JSON scalar without guessing units.

        The trimmed text input becomes a boolean, integer, float, or unchanged
        string used in a STAC Query extension expression.
        """

        value = value.strip().strip("\"'")
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", value):
            return float(value)
        return value

    def _search_payload(
        self,
        query: str,
        collection_id: str,
        limit: int,
        schema: dict[str, Any] | None = None,
        product_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
        """Parse dates, bbox, and observed metadata comparisons into STAC Search.

        Free-form query, optional collection and result limit are inputs. The
        output contains a valid Search payload plus unsupported field phrases.
        """

        schema = schema or self._schema(collection_id)
        available = set(schema["observed_item_properties"])
        payload: dict[str, Any] = {"limit": min(limit, self.valves.server_page_limit)}
        if collection_id:
            payload["collections"] = [collection_id]
        if product_ids:
            payload["ids"] = product_ids

        bbox_match = re.search(
            r"(?:bbox|bounding box)\s*[:=]?\s*\[?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]?",
            query,
            re.IGNORECASE,
        )
        if bbox_match:
            bbox = [float(value) for value in bbox_match.groups()]
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise ValueError("bbox must be min-x, min-y, max-x, max-y")
            payload["bbox"] = bbox

        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?\b", query)
        for value in dates:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(dates) >= 2:
            payload["datetime"] = f"{dates[0]}/{dates[1]}"
        elif len(dates) == 1:
            if re.search(r"\b(after|since|from)\b", query, re.I):
                payload["datetime"] = f"{dates[0]}/.."
            elif re.search(r"\b(before|until|through)\b", query, re.I):
                payload["datetime"] = f"../{dates[0]}"
            else:
                payload["datetime"] = dates[0]
        else:
            years = re.findall(r"\b(?:19|20)\d{2}\b", query)
            if len(set(years)) > 1:
                raise ValueError(f"Query contains multiple bare years; provide an explicit date range: {sorted(set(years))}")
            if years:
                year = years[0]
                payload["datetime"] = f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z"

        operator_map = {"=": "eq", "==": "eq", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "!=": "neq"}
        comparisons: dict[str, dict[str, Any]] = {}
        unsupported: list[str] = []
        pattern = re.compile(r"([A-Za-z][A-Za-z0-9_:\- ]{0,80}?)\s*(<=|>=|!=|==|=|<|>)\s*(.+)", re.I)
        for segment in re.split(r"\s+\band\b\s+|[,;]", query, flags=re.I):
            match = pattern.search(segment.strip())
            if not match:
                continue
            phrase, operator, value = match.groups()
            phrase = re.sub(r"^.*?\b(?:where|with|having)\s+", "", phrase.strip(), flags=re.I)
            phrase = re.sub(r"^(?:(?:find|search|list|show|items?|products?)\b\s*)+", "", phrase, flags=re.I)
            value = re.split(
                r"\s+\b(?:between|before|after|since|from|until|through|bbox|bounding box)\b",
                value,
                maxsplit=1,
                flags=re.I,
            )[0]
            if phrase.lower() in {"bbox", "bounding box", "date", "datetime", "collection"}:
                continue
            field = self._resolve_field(phrase, available)
            if not field:
                unsupported.append(phrase)
                continue
            comparisons.setdefault(field, {})[operator_map[operator]] = self._typed(value)

        for alias_phrase in ("sun incidence angle", "incidence angle", "sun incidence", "cloud cover", "sensor"):
            if any(self._resolve_field(key, available) in comparisons for key in [alias_phrase]):
                continue
            match = re.search(rf"\b{re.escape(alias_phrase)}\s+(?:is\s+)?([A-Za-z0-9_.:+\-]+)", query, re.I)
            if match:
                if match.group(1).lower() in {
                    "angle", "for", "from", "in", "of", "value", "values", "valuese", "where", "with"
                }:
                    continue
                field = self._resolve_field(alias_phrase, available)
                if field:
                    comparisons[field] = {"eq": self._typed(match.group(1))}
                else:
                    unsupported.append(alias_phrase)
        inferred_filters, inferred_terms = self._observed_term_filters(query, schema)
        for field, expression in inferred_filters.items():
            comparisons.setdefault(field, expression)
        if comparisons:
            payload["query"] = comparisons
        return payload, sorted(set(unsupported)), inferred_terms

    def _search_all(self, payload: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], int | None, bool]:
        """Follow STAC next links until the requested cap or the result set ends."""

        document = self._json("/search", payload)
        features: list[dict[str, Any]] = []
        matched: int | None = document.get("numberMatched")
        if matched is None and isinstance(document.get("context"), dict):
            matched = document["context"].get("matched")
        seen: set[str] = set()
        truncated = False
        while True:
            page = [feature for feature in document.get("features", []) if isinstance(feature, dict)]
            remaining = limit - len(features)
            features.extend(page[:remaining])
            next_links = [
                link
                for link in document.get("links", [])
                if isinstance(link, dict) and link.get("rel") == "next" and link.get("href")
            ]
            if len(page) > remaining:
                truncated = True
                break
            if not next_links:
                break
            if len(features) >= limit:
                truncated = True
                break
            link = next_links[0]
            signature = json.dumps(link, sort_keys=True, default=str)
            if signature in seen:
                truncated = True
                break
            seen.add(signature)
            if str(link.get("method", "GET")).upper() == "POST":
                body = link.get("body") if isinstance(link.get("body"), dict) else payload
                if link.get("merge") is True and body is not payload:
                    body = {**payload, **body}
                document = self._json(str(link["href"]), body)
            else:
                document = self._json(str(link["href"]))
        if matched is not None and matched > len(features):
            truncated = True
        return features, matched, truncated

    def _execute(
        self,
        query: str,
        operation: Literal["auto", "list_collections", "list_items", "search", "schema"] = "auto",
        collection_id: str = "",
        limit: int = 50,
        product_ids: list[str] | None = None,
        return_fields: list[str] | None = None,
        __user__: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """Run one schema-aware STAC operation in a worker thread.

        Use natural language plus optional collection. Metadata comparisons may
        use forms such as ``cloud cover < 10`` or ``instrument=tir``; bbox uses
        four numbers and ISO dates form a date/range. The Tool inspects actual
        catalog properties first and reports unsupported fields explicitly.

        :param query: Natural-language catalog request, including desired filters.
        :param operation: Usually auto; explicitly choose listing, schema, or search when known.
        :param collection_id: Optional exact collection ID to constrain items/schema/search.
        :param limit: Maximum returned records, capped by admin and user Valves.
        :param product_ids: Optional exact product/item IDs; labelled IDs in the query are also recognized.
        :param return_fields: Optional schema-backed properties to return exactly for every matched product.
        :return: Parsed STAC parameters, item IDs, projected values, truncation state, and explicit diagnostics.
        """

        if not query.strip():
            raise ValueError("query must describe the requested catalog operation")
        user_limit = getattr((__user__ or {}).get("valves"), "max_results", limit)
        selected_limit = max(1, min(limit, user_limit, self.valves.server_page_limit))
        selected_operation = self._operation(query, operation)
        if selected_operation == "list_collections":
            collections = self._collections()[:selected_limit]
            return {
                "operation": selected_operation,
                "collections": [
                    {"id": item.get("id"), "title": item.get("title"), "description": item.get("description")}
                    for item in collections
                ],
            }
        if not collection_id:
            collection_id = self._infer_collection(query)
        if selected_operation == "schema":
            return {"operation": selected_operation, **self._schema(collection_id)}
        selected_ids = self._product_ids(query, product_ids)
        if selected_operation == "list_items":
            schema = self._schema(collection_id, selected_ids)
            payload, unsupported, inferred_terms = self._search_payload(
                query, collection_id, selected_limit, schema, selected_ids
            )
            if unsupported:
                return {
                    "operation": selected_operation,
                    "status": "unsupported_fields",
                    "unsupported_fields": unsupported,
                    "observed_schema": schema,
                }
            features, matched, truncated = self._search_all(payload, selected_limit)
            return {
                "operation": selected_operation,
                "status": "ok",
                "collection_id": collection_id or None,
                "search_parameters": payload,
                "inferred_observed_terms": inferred_terms,
                "item_ids": [feature.get("id") for feature in features],
                "returned": len(features),
                "matched": matched,
                "truncated": truncated,
            }

        schema = self._schema(collection_id, selected_ids)
        requested_fields, unsupported_outputs, field_mappings = self._requested_fields(
            query, set(schema["observed_item_properties"]), return_fields
        )
        payload, unsupported_filters, inferred_terms = self._search_payload(
            query, collection_id, selected_limit, schema, selected_ids
        )
        unsupported = sorted(set(unsupported_outputs + unsupported_filters))
        if unsupported:
            return {
                "operation": "search",
                "status": "unsupported_fields",
                "unsupported_fields": unsupported,
                "observed_schema": schema,
                "message": "One or more requested fields were not observed. Update the alias Valve or use an actual property name.",
            }
        features, matched, truncated = self._search_all(payload, selected_limit)
        response: dict[str, Any] = {
            "operation": "search",
            "status": "ok",
            "search_parameters": payload,
            "inferred_observed_terms": inferred_terms,
            "matched": matched if matched is not None else len(features),
            "returned": len(features),
            "limit_applied": selected_limit,
            "truncated": truncated,
            "items": [
                {
                    "id": feature.get("id"),
                    "collection": feature.get("collection"),
                    "datetime": (feature.get("properties") or {}).get("datetime"),
                }
                for feature in features
            ],
        }
        if requested_fields:
            values_by_product: list[dict[str, Any]] = []
            missing: list[dict[str, str]] = []
            distinct: dict[str, list[Any]] = {field: [] for field in requested_fields}
            distinct_keys: dict[str, set[str]] = {field: set() for field in requested_fields}
            for feature in features:
                properties = feature.get("properties") or {}
                values: dict[str, Any] = {}
                missing_fields: list[str] = []
                for field in requested_fields:
                    value = properties.get(field)
                    values[field] = value
                    if field not in properties or value is None:
                        missing_fields.append(field)
                        missing.append({"product_id": str(feature.get("id")), "field": field})
                        continue
                    key = json.dumps(value, sort_keys=True, default=str)
                    if key not in distinct_keys[field]:
                        distinct_keys[field].add(key)
                        distinct[field].append(value)
                values_by_product.append(
                    {
                        "product_id": feature.get("id"),
                        "collection": feature.get("collection"),
                        "values": values,
                        "missing_fields": missing_fields,
                    }
                )
            response.update(
                {
                    "requested_fields": field_mappings,
                    "values_by_product": values_by_product,
                    "distinct_values": distinct,
                    "missing_values": missing,
                }
            )
        if selected_ids:
            returned_ids = {str(feature.get("id")) for feature in features}
            unresolved_ids = [value for value in selected_ids if value not in returned_ids]
            response["not_found_product_ids"] = [] if truncated else unresolved_ids
            response["unresolved_product_ids"] = unresolved_ids if truncated else []
        return response

    async def stac_catalog(
        self,
        query: str,
        operation: Literal["auto", "list_collections", "list_items", "search", "schema"] = "auto",
        collection_id: str = "",
        limit: int = 50,
        product_ids: list[str] | None = None,
        return_fields: list[str] | None = None,
        __user__: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """List, inspect, or search the configured STAC catalog in one call.

        Use natural language plus optional collection. Metadata comparisons may
        use forms such as ``cloud cover < 10`` or ``instrument=tir``; bbox uses
        four numbers, ISO dates form a date/range, and a bare year selects that
        calendar year. Product ID lists and requested value fields may be stated
        in the query or supplied explicitly. Actual catalog properties are
        inspected first and unsupported or missing fields are reported.

        :param query: Natural-language catalog request, including desired filters.
        :param operation: Usually auto; explicitly choose listing, schema, or search when known.
        :param collection_id: Optional exact collection ID to constrain items/schema/search.
        :param limit: Maximum returned records, capped by admin and user Valves.
        :param product_ids: Optional exact product/item IDs; natural-language labelled IDs are also recognized.
        :param return_fields: Optional metadata fields whose exact per-product values should be returned.
        :return: Collection/item IDs, parsed parameters, projected values, missing values, and unsupported-field diagnostics.
        """

        return await asyncio.to_thread(
            self._execute,
            query,
            operation,
            collection_id,
            limit,
            product_ids,
            return_fields,
            __user__,
        )
