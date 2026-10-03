---
type: decision
status: accepted
created: 2026-10-03
updated: 2026-10-03
tags: [get-brolls, catalogs, search, planning]
---

# Plan a catalog search chain for each scenario fragment

The managing agent chooses a separate ordered search chain for each search fragment. Each initial chain contains 1-5 catalogs, normally 2-3, with a concrete reason for including each catalog and the material expected there. Search follows the selected order, making source priorities depend on the fragment while keeping the route explicit.

A single catalog is appropriate when the exact source is known, such as a particular recording, speech, or archive item. Two or three catalogs are the usual plan for a fragment; four or five are appropriate for difficult searches involving rare events, historical material, multiple countries, or different languages. The upper bound preserves useful alternatives without requiring catalogs to be added merely to fill the chain.

The planning and search rules below and an integrated rollout covering the complete target catalog inventory are accepted; this record does not change runtime behavior.

## One level of search fragments

The managing agent selects search fragments directly from the original scenario in one step, choosing each fragment's scope according to its visual purpose. Each selected fragment has its own catalog chain and three-option target. This is a single level of search tasks, without a separate recursive subdivision stage.

## Successful search target

A search reaches its success target when the managing agent has three suitable, distinct options for the search fragment to present for human review. Finding a single suitable option does not fulfill this target. A bounded search may finish short of the target under the exhaustion rule below.

## Distinct options

Different relevant scenes, camera angles, actions, or moments can be separate editorial options, including when they come from the same recording or catalog. Reposts, near-identical trims, and small shifts in the boundaries of the same shot count as a single option. Differences must provide a meaningful choice of visual material for the fragment.

## Visual confirmation of suitability

An option counts toward the target only after the managing agent has viewed the actual material or a preview, confirmed what is visible, and assessed how it matches the search fragment. Titles, descriptions, and metadata guide discovery and selection for inspection; they are insufficient on their own to count an option as suitable. This assessment prepares a proposal for human review, while approval remains a human decision.

## Per-catalog query limit

The initial rule allows at most three meaningfully different search queries per catalog for the search fragment. A search attempt consists of a query and assessment of its returned results, rather than one viewed video or preview frame. Useful query variations include precise event/person/place/date terms, another formulation or name spelling, and an appropriate source language or broader wording that preserves the required context.

If the target of three suitable, distinct options has not been reached after the catalog's query allowance, move to the next catalog in the selected chain. Keep suitable options already found and accumulate the remaining options across catalogs. Stop once three suitable, distinct options have been found and visually confirmed; move on earlier if access is unavailable or the catalog clearly does not fit the task.

This is a total allowance per catalog, including queries that produce fewer than the three required options. An initial five-catalog chain therefore permits at most fifteen such search queries.

## Query language choice

The managing agent chooses query languages according to the catalog, event, country, and original names. It may translate or reformulate a query within the existing three-query allowance per catalog; language changes do not create an additional allowance. There is no mandatory Russian-to-English-to-local-language sequence.

## One additional pass

If the initial chain has been exhausted before the target is reached, the managing agent may plan one additional chain of other suitable catalogs. The additional chain follows the same chain-size, selection-reason, per-catalog query-limit, distinctness, and visual-confirmation rules. Retain options found in the initial pass and stop as soon as three suitable, distinct options have been accumulated.

After the additional chain has been exhausted, present the actual verified options and explain any shortfall from three. The agent does not start a further autonomous pass. If no other suitable catalogs are available, present the actual result without inventing another chain. Two five-catalog chains permit at most thirty meaningfully different search queries for a fragment.

## Integrated rollout

The accepted development scope covers all twenty catalogs in the source reference and the accepted search behavior in one integrated effort. Shared catalog guidance, capability reporting, chain execution, query accounting, and option review are built once and reused by the source integrations.

Integrations are grouped by their retained access routes: public catalog APIs, credentials/session-based routes, and browser or locator routes. An early Archive.org end-to-end check validates the shared integration contract within this effort; development of the remaining catalog routes continues as part of the same scope.

Each integration retains its actual source-specific capabilities and access requirements. Adapter implementation and local test results are recorded separately from configured access and successful live acquisition evidence. Browser and locator routes retain their documented role instead of implying an unsupported universal search or download API.

Implementation work will define how chain plans, query languages, outcomes, and consumed allowances are recorded within the existing project workflow. Those storage details do not require another product-policy interview.

## Deferred acquisition question

Whether a visually confirmed option requiring a separately requested original counts toward the three-option target is deferred until a concrete case requires this distinction. Catalog-specific footage-request routes and conditions remain in the source reference.

## References

- [Catalog search language](../../CONTEXT.md)
- [Source catalogs and current integration status](../SOURCE-CATALOGS.md)
