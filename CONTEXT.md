---
type: reference
status: current
created: 2026-10-03
updated: 2026-10-03
tags: [get-brolls, catalogs, domain-model]
---

# Catalog search language

Domain terms used when designing searches for scenario fragments. Catalog-specific routes are described in [SOURCE-CATALOGS.md](docs/SOURCE-CATALOGS.md); user-facing wording is covered by [glossario.md](references/glossario.md).

## Language

**Search fragment**:
A portion selected directly from the original scenario as one visual search task. Its scope is chosen according to meaning.
_Avoid_: Query, subfragment

**Search query**:
A formulation submitted to a catalog to find material for a search fragment. Its language can differ from the scenario language.
_Avoid_: Scenario line, search fragment

**Search chain**:
An ordered list of catalogs selected for one search fragment.
_Avoid_: Global catalog order

**Search option**:
A distinct editorial choice of visual material for a search fragment. Different relevant scenes or moments from the same recording can be separate options.
_Avoid_: Catalog, repost

**Duplicate option**:
The same visual material represented by a repost, a near-identical trim, or a small shift in the boundaries of the same shot.
_Avoid_: Alternative scene

**Suitable option**:
A search option whose visible content has been inspected in the actual material or a preview and assessed as matching the search fragment.
_Avoid_: Promising search hit, human-approved option

**Search attempt**:
One meaningfully different search query and assessment of its returned results for a search fragment.
_Avoid_: Viewed video, preview frame, repeated identical query

**Search pass**:
Traversal of one planned search chain for a search fragment.
_Avoid_: Search query, catalog
