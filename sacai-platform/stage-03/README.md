# Stage 3 — general STAC Tool

Install `../openwebui_tools/stac_catalog.py` through Workspace → Tools. In its
Valves set the current STAC URL, timeout, TLS policy, field aliases, and page
limits. No container restart is needed for a stored Valve change.

The same single entry point also accepts exact `product_ids` and `return_fields`
arguments. In natural language it recognizes labelled product/item-ID lists,
bare years, collection IDs/titles/acronyms such as TMC, and unique scalar terms
observed in live collection summaries or sampled item metadata. A request for
field values returns `values_by_product`, `distinct_values`, `missing_values`,
and `not_found_product_ids`. It follows STAC `next` links up to the configured
cap and sets `truncated=true` if more matches remain.

Acceptance examples:

- `Give me all values for sun incidence for product IDs ID-1, ID-2`
- `Give me sun incidence values for products from 2020 TMC`
- `List products from 2020 TMC`

First run schema inspection and ensure the `sun incidence` Valve alias points
to the property actually exposed by this catalog (the default is
`view:incidence_angle`). Then list collections, combine collection/date/bbox and
metadata comparisons, exercise both examples above, and request a nonexistent
property. The last call must return `unsupported_fields`, not an invented
match. Missing per-item values and unknown product IDs must also be explicit.
Confirm this is the only enabled catalog Tool.
