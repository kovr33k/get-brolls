---
type: specification
status: accepted
created: 2026-10-03
updated: 2026-10-03
tags: [get-brolls, catalogs, search, integration]
---

# Integrate twenty catalogs with fragment-specific search chains

## Problem Statement

A creator needs a small, useful choice of footage for each visually meaningful part of a scenario. The current collection workflow searches a limited provider set, uses a shared provider order for automatic discovery, and stops after collecting enough search hits. A hit does not establish what the material actually shows, whether it matches the scenario, or whether it offers a different editorial choice.

The target catalog inventory includes public APIs, keyed APIs, authorized account sessions, browser discovery, and archive locators. Most retained routes are not integrated into this checkout. A catalog listing, a configured key, or a successful mock test does not establish working search, preview, or acquisition. Integrating sources one by one as separate product rollouts would also prolong the work unnecessarily.

## Solution

Implement the complete twenty-catalog inventory and the accepted search behavior in one integrated development effort. Build shared planning, capability reporting, query accounting, and option review once, then connect each catalog through its actual retained route. Use an early Archive.org end-to-end check to exercise the shared workflow within this effort; continue the other integrations as part of the same scope.

The managing agent selects search fragments directly from the original scenario. For each fragment it chooses an ordered search chain of one to five suitable catalogs, normally two or three, and explains why each catalog belongs there. It chooses query wording and languages according to the material being sought. There is no recursive subdivision stage or fixed global catalog ranking.

The target is three suitable, distinct search options per fragment. The agent counts an option only after viewing the actual material or a preview and confirming its visual match. It keeps useful options while moving through the chain, submits at most three meaningfully different queries per catalog, and stops when the target is reached. If the initial chain is exhausted, it may choose one additional chain of other suitable catalogs. After that, it presents the verified options and any shortfall. Human approval and reuse conditions remain separate gates before final acquisition and delivery.

## User Stories

1. As a creator, I want the agent to select search fragments directly from my scenario, so that visual search follows the meaning of the text without another subdivision workflow.
2. As a creator, I want each search fragment to keep its original narration and visual purpose, so that I can understand why a proposed option belongs there.
3. As a managing agent, I want to choose a separate search chain for each fragment, so that source selection fits that fragment rather than a global order.
4. As a creator, I want a short reason for each chosen catalog, so that I can assess the planned search route.
5. As a managing agent, I want one to five catalogs in a chain, normally two or three, so that I can use an exact known source or expand a difficult search without padding the plan.
6. As a managing agent, I want catalog guidance describing useful material and actual access routes, so that I can make flexible choices instead of applying rigid topic rules.
7. As a creator, I want all twenty retained catalogs included in one integration effort, so that I do not have to commission a separate rollout for every source.
8. As a managing agent, I want queries in languages appropriate to the source, event, country, and original names, so that translated wording does not hide useful material.
9. As a creator, I want language changes to stay within the same three-query allowance, so that multilingual searching does not silently multiply the search budget.
10. As a managing agent, I want up to three meaningfully different queries per catalog, so that I can refine a search before moving on.
11. As a creator, I want attempts to represent queries and their result assessment, so that viewing several candidates does not consume the query allowance incorrectly.
12. As a managing agent, I want to move on early when a catalog is inaccessible or clearly unsuitable, so that I do not waste the remaining attempts there.
13. As a creator, I want access failures, limited coverage, and empty results distinguished, so that I am not told that footage does not exist when the search was incomplete.
14. As a creator, I want three suitable, distinct options for each fragment, so that I can make a meaningful editorial choice.
15. As a creator, I want the agent to view actual material or a preview before counting it, so that titles and descriptions alone do not become proposed footage.
16. As a creator, I want different relevant scenes or moments from one recording to count as separate options, so that a useful source can supply more than one editorial choice.
17. As a creator, I want reposts and near-identical trims to count as one option, so that duplicated material does not fill the target.
18. As a managing agent, I want to retain suitable options across catalogs and passes, so that changing sources does not discard useful work.
19. As a managing agent, I want to stop when three suitable options have been confirmed, so that the search does not continue unnecessarily.
20. As a managing agent, I want one additional chain of other suitable catalogs after the first is exhausted, so that I can recover from a poor initial route within a bounded search.
21. As a creator, I want the actual verified count and a shortfall explanation after exhaustion, so that the agent does not invent options or search indefinitely.
22. As a creator, I want an interrupted search to resume with its plan, options, and consumed allowances, so that restarting does not repeat completed work or reset limits.
23. As a creator, I want API keys and session settings loaded from private configuration, so that the integrations can use the access I provide without exposing credentials.
24. As a creator, I want missing or invalid access reported for the affected catalog, so that other suitable sources can still be used.
25. As a creator, I want Telegram search confined to my explicit public-channel list, so that authorizing my account does not expand the search to private conversations or all subscriptions.
26. As a creator, I want the retained Grok OAuth route preserved for X discovery, so that integration does not silently switch to a paid API-key route.
27. As a creator, I want Instagram and TikTok to use their documented browser and post-URL routes, so that the agent can use available sessions without claiming nonexistent CLI keyword search.
28. As a creator, I want location-specific Mapillary images and GDELT television references identified by their actual roles, so that they are not presented as interchangeable footage downloads.
29. As a creator, I want browser and archive-locator results to enter the common candidate workflow, so that I can review their provenance and access limitations alongside API results.
30. As a creator, I want canonical pages, original item IDs, creators, dates, and relevant intervals preserved, so that I can trace a selected option back to its source.
31. As a creator, I want exact catalog shots and their parent recordings distinguished, so that acquisition uses the intended interval once and does not select the wrong footage.
32. As a creator, I want preview availability, original availability, and reuse conditions reported separately, so that playable material is not treated as cleared editing media.
33. As a creator, I want the existing Storyboard and human decision workflow reused, so that search integration does not introduce another review application.
34. As a creator, I want unsuitable hits retained as search history without appearing as suitable options, so that progress reflects actual visual confirmation.
35. As a creator, I want relevant changes to a source, interval, or scenario context to invalidate stale confirmation and approval, so that previous decisions do not silently apply to different material.
36. As a maintainer, I want existing projects, single-provider commands, and local imports to remain usable, so that the new workflow does not break established collection paths.
37. As a maintainer, I want deterministic offline tests with synthetic media and provider fixtures, so that ordinary verification does not depend on credentials or live services.
38. As a maintainer, I want separate dated live evidence for each implemented route, so that local tests are not reported as proof of actual access or acquisition.
39. As a creator, I want real previews for a representative scenario reviewed together, so that acceptance measures whether the integration produces useful choices for my work.

## Implementation Decisions

1. **Agent responsibility and execution responsibility.** The managing agent selects fragments, catalogs, queries, languages, and editorial options. The CLI validates and persists the chosen plan, accounts for attempts, exposes the next permitted action, and enforces exhaustion. Do not introduce another autonomous planning service or a required new model subscription.
2. **Reuse the existing fragment identity.** Represent search fragments through the existing brief/beat and shot association. Preserve narration and target context. Add the minimum optional plan and progress data needed; do not require a second fragment hierarchy or migrate old briefs just to read them.
3. **Plan contract.** Store the ordered catalog entries, inclusion reasons, expected material, fragment context, and pass identity. Validate one to five distinct catalogs per chain and honor allowed sources, media needs, and existing project policies. The additional chain uses other suitable catalogs; it does not repeat the initial chain to replenish allowances.
4. **Execution contract.** Associate every dispatched query with its fragment, pass, catalog, wording, language when known, and outcome. Permit no more than three meaningfully different queries per catalog. Different wording automatically generated by an existing query-shortening fallback also consumes this allowance when used inside a chain. Repeating the same query or retrying its transport does not create another allowance; transport retries remain bounded under the existing recovery policy.
5. **Search progress.** Expose the current catalog, consumed and remaining query allowance, accumulated suitable options, actual access/coverage outcomes, and whether the search reached its target or exhausted its permitted chains. Result count alone cannot mark success. At most two five-catalog chains allow thirty meaningfully different queries per fragment; this is not a promise of thirty HTTP requests or a bound on preview bytes.
6. **Resume contract.** Persist plans and query progress with the existing project ledger, events, and recoverable write facilities. Record dispatch and interrupted/uncertain outcomes so a restart cannot reset an allowance or silently launch another pass. Keep projects and media outside the distributed skill source. Avoid a new database or background scheduler unless the existing storage demonstrably cannot satisfy recovery.
7. **Suitable-option evidence.** Persist the material or preview actually viewed, the relevant interval or still image, the visual observation, and the explanation of its match to the fragment. Creating a preview file or resolving metadata does not constitute viewing it. The managing agent records visual confirmation explicitly; it must not write human approval as part of that action.
8. **Distinctness.** Group reposts, near-identical trims, and small boundary shifts of the same shot as one option. Preserve original IDs, hashes when available, intervals, and editorial distinctness reasons. Different relevant scenes, angles, actions, or moments may count separately even within one recording. Do not require a vector index or a new embedding model for this decision.
9. **Confirmation lifecycle.** Tie suitable-option evidence to the fragment context and the actual material representation and interval. Invalidate or require renewed confirmation when those change materially. Preserve the existing independent human approval signature and rights/acquisition gates. Rejected or stale options do not remain in the current suitable-option count.
10. **Shared catalog capabilities.** Extend existing provider capability reporting and routing to distinguish supported discovery, URL/item resolution, preview, technical acquisition, and locator/manual routes. Report implementation support, configured access, and observed live results separately. Expand source validation, schemas, brief guidance, and acquisition routing consistently; a catalog name in a registry is insufficient integration.
11. **Source coverage.** The following table defines the retained route for all twenty catalogs. Detailed catalog metadata and special access rules remain in the catalog reference rather than being duplicated here.

    | Catalog | Retained integration route | Required distinction |
    |---|---|---|
    | YouTube | Existing yt-dlp discovery and acquisition | No YouTube API key prerequisite; preserve literal-source selection |
    | Wikimedia Commons | Public MediaWiki discovery and file resolution | Inspect the selected file and its item-specific reuse evidence |
    | Internet Archive | Public catalog search, item metadata, file selection | Select the actual item/file representation and retain its context |
    | NASA Image and Video Library | Public Images API discovery and asset resolution | No general NASA key prerequisite; distinguish images from videos |
    | Library of Congress | Public JSON catalog and item resources | Resolve actual resources instead of treating a search thumbnail as an original |
    | DVIDS | Keyed search and asset/file resolution | Search/read access does not require upload permissions |
    | Europeana | Keyed discovery and holding-institution resources | A catalog record does not guarantee a downloadable original |
    | NARA | Keyed catalog, record, and digital-object resolution | API storage conditions and original-media rights are separate |
    | Pexels | Existing keyed video discovery and asset refresh | Preserve stock policy; do not imply implemented photo search |
    | Pixabay | Existing keyed video discovery and asset refresh | Preserve stock policy and actual media dimensions |
    | Mapillary | Token-based geographic image search | Requires a real place or coordinates; street images are not moving footage |
    | Telegram | Telethon user session and explicit public-channel whitelist | Bounded history/text search; keep message and attachment identity |
    | GDELT TV | Public television search and timing references | A locator result is not an acquired editing original |
    | X | Retained Grok OAuth discovery through xAI X Search | Independently verify OAuth/tool access, refresh, original posts, and media retrieval |
    | EC Audiovisual Service | Retained AV Portal client/backend route | Exact shots, parent assets, source offsets, and download restrictions |
    | UN Web TV | Transcript discovery, catalog/direct assets, player representations | Transcript coverage and older-video fallback remain distinct |
    | UN Audiovisual Library | Public archive cards, direct item import, request links | Archive locator and requested-original route; no invented universal API |
    | Destockd | Website discovery and direct shot-link import | Preserve shot-to-Archive linkage; undocumented API use requires operator agreement |
    | Instagram | Authorized browser discovery and retained Reel acquisition | Match video and audio to the same Reel; no claimed global CLI keyword API |
    | TikTok | Browser discovery, full canonical post URL, yt-dlp | No claimed global CLI keyword API; access can depend on the selected item |

12. **Browser and locator participation.** Such catalogs may participate in a chain through their supported route. Record meaningful browser searches and imported results in the same plan/progress contract. When interaction cannot be performed, report that limitation and advance or present a shortfall; do not fabricate an API or silently change the route. Local media remains an import route outside the twenty-catalog count.
13. **Configuration compatibility.** Extend the explicit environment allowlist for DVIDS, Europeana, NARA, Mapillary, and Telegram credentials and channel settings. Retain the supplied names: `DVIDS_API_KEY`, optional `DVIDS_CLIENT_SECRET`, `EUROPEANA_API_KEY`, `NARA_API_KEY`, `MAPILLARY_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, and `BROLL_TELEGRAM_CHANNELS`. Accept optional `GEMINI_API_KEY` and `XAI_API_KEY` without making them required or automatically using API billing. Preserve existing stock/YouTube keys, process-environment precedence, explicit environment-file selection, and rejection of genuinely unknown settings. Do not expose values in diagnostics.
14. **Telegram setup.** Validate the API ID/hash and an explicit user-session reference, resolving session storage to a private location outside the distributed skill source. A session name/reference is not proof of authorization: verify it and provide a local interactive login path when necessary, including account 2FA. Support the supplied inline channel-list configuration with a documented format. Limit discovery to its selected public channels and the relevant search period, retain a history cursor, and handle rate waits without expanding account scope.
15. **X setup.** Validate the retained Grok OAuth mode, supported model/tool, expiry, and refresh or re-login. Public API-key documentation alone does not prove the subscription/OAuth route works. Report it as unverified or unavailable until a bounded live probe succeeds. Original-post verification, screenshots, and media download have their own capability results; do not substitute a different X API integration silently.
16. **Source-specific timing and access.** Preserve EC shot identity separately from its parent recording, apply provider source offsets exactly once, and keep acquisition restrictions distinct from rights. Respect the UN transcript coverage window and use older catalog/direct assets when appropriate. Keep Destockd's website/link route until programmatic access is agreed. Revalidate retained unversioned endpoints before enabling their adapters.
17. **Provenance and media.** Preserve canonical source page, original item and asset identity, creator, source date/location when available, actual representation, interval/timing, and known acquisition constraints. Unknown fields remain unknown. Prefer real 1080p where available; do not upscale to claim source quality. Keep credentials, cookies, session material, and signed transport URLs out of shared reports and exported review data.
18. **Common review and delivery.** Route options through the existing candidate, inspect, preview, Storyboard, human review, rights, fetch, and verification workflow. Separate raw hits from visually confirmed choices in summaries. Preserve the ready-preview review view and its scenario narration; keep product interface text English and source/scenario content in its original language.
19. **Backward compatibility.** Preserve explicit single-provider search, URL resolution, local import, old briefs/manifests, dry-run behavior, and serial writes. The new chain workflow must not silently change ordinary commands into autonomous multi-pass searches. Keep status genuinely read-only, including when showing new search progress.
20. **Documentation and completion evidence.** Update the canonical skill, regenerate its mirror, and update the operational guide, catalog support status, configuration examples, and changelog with implementation. Record each source's implemented route and its separately observed access/acquisition evidence. Manual or unavailable routes remain explicit; do not claim all twenty have automated keyword search or download.

## Testing Decisions

The accepted test approach combines offline checks of search rules with real catalog and media checks. The primary test seam is the existing audited CLI command boundary and the resulting project state. Reuse it to exercise chain execution, option counting, progress, and resume behavior with synthetic catalog results and media. Provider response parsing and browser/session transports receive focused contract tests at their existing external-call boundaries. Bounded live probes and editorial review of actual material are separate acceptance evidence.

A good test asserts externally observable behavior: which permitted query was sent, what came back, what was persisted, what the next action is, and what the creator sees. It should fail when a limit, identity, recovery guarantee, or human decision gate breaks. Do not test a particular class layout, private helper arrangement, or prose-only routing guess.

Prior art includes existing audited search-command tests with temporary ledgers and mocked provider results, offline provider JSON fixtures, brief/shot association tests, synthetic-media preview tests, read-only status checks, and opt-in network tests. Extend these patterns rather than building a parallel harness.

1. **Independent fragments and plans:** two fragments retain different chains and reasons; one-source exact plans are valid; empty, oversized, duplicated, disallowed, or incompatible plans receive useful validation errors.
2. **Query allowance:** a catalog receives no fourth meaningful query. Language changes and shortened formulations use the same allowance. Identical-query transport retries cannot renew it. Viewing multiple candidates does not consume extra queries.
3. **Target counting:** many metadata hits and generated-but-unviewed previews cannot fulfill the target. Three distinct viewed matches can fulfill it while human approval remains pending.
4. **Distinctness:** reposts and shifted trims contribute one option; different relevant scenes from the same source can contribute multiple options. Unsupported distinctness claims are visible for review.
5. **Transitions:** suitable options survive catalog changes; inaccessible sources can be skipped early; reaching the target stops later dispatches. Exhaustion permits one additional disjoint chain and no third autonomous pass.
6. **Shortfalls and coverage:** zero, one, and two suitable-option outcomes report their actual counts. Access errors and incomplete date/collection coverage cannot be rendered as proof of missing footage.
7. **Resume and interrupted writes:** restarting preserves dispatched attempts, consumed allowances, options, pass identity, and an interrupted outcome without multiplying candidates or resetting limits. Exercise recovery through persisted state, including a failed write or interrupted dispatch.
8. **Confirmation and approval:** changing a relevant interval, representation, or scenario context invalidates stale suitability evidence; existing human approval invalidation still applies. Visual confirmation alone cannot pass final acquisition gates.
9. **All-source contract coverage:** every catalog in the twenty-row inventory has a tested supported entry route and accurate capabilities. Unsupported operations receive a clear limitation; they must not pass by returning invented data or pretending manual access is automated.
10. **API adapters:** synthetic fixtures cover selected item/file resolution, missing fields, image/video distinctions, errors, and bounded transport recovery. Source-specific coverage includes EC parent/shot offsets and restrictions, UN recent-versus-old discovery, and locator/original identity.
11. **Credentials and sessions:** missing keys, invalid access, expired sessions, an unauthenticated Telegram session reference, and required local login are reported per route. Telegram cannot search outside the whitelist. Secrets are absent from errors, logs, exports, and fixture data.
12. **Configuration:** all documented new settings parse without relaxing unknown-key rejection; optional unused keys and empty API-key alternatives do not select another billing mode. Existing environment precedence and explicit configuration paths remain unchanged.
13. **Existing behavior:** run relevant regressions for single-provider commands, old brief/manifest loading, shot links, preview/review, rights and human approval, local imports, dry-run, and status. Verify status without creating a project tree, recovering writes, or taking the exclusive project lock.
14. **Dated live probes:** outside the distributed source, exercise each automated route with bounded queries and selected material. Record public source URL, software version/date, actual result, preview/acquisition outcome, media dimensions/duration when applicable, and observed limitations. For browser and locator routes, validate their actual supported discovery/import workflow. A capability remains unverified when prerequisites or provider access prevent a probe.
15. **Editorial acceptance:** review a representative scenario as a batch of real previews, compare options with their fragment narration, and check visual match and distinctness. Inspect the actual failure/shortfall cases. Mock results, capability tables, and a green test suite cannot replace this review.
16. **Release verification:** run the repository's installer prerequisite check, doctor, full offline suite, packaging/mirror checks, documented command help checks, and required operating-system CI before integration into production. Doctor is diagnostics, not evidence of successful media acquisition. Do not run live checks as part of the default offline suite.

## Out of Scope

- A second fragment hierarchy, rigid topic-to-catalog rules, mandatory alternative classes, or extra editorial taxonomies.
- New vector retrieval, embedding infrastructure, a mandatory external vision model, or another autonomous agent service.
- Whole-catalog crawling, private Telegram conversations, account-wide search beyond the explicit channel whitelist, or protection bypass.
- A universal keyword-search or download API for catalogs whose retained route is browser-based or a locator.
- Automatic switches from Grok OAuth to API billing, automatic human approval, or treating technical access as reuse permission.
- Automatic archive correspondence, licensing/payment, or procurement of requested originals. Retain locator/request information and existing import support.
- Deciding whether a visually confirmed option requiring a separately requested original counts toward the three-option target; the accepted ADR defers that question until a concrete case requires it.
- Adding Coverr or Unsplash, treating local imports or UNifeed as additional catalog integrations, or importing unrelated project features.
- Publishing credentials, installing personal skill copies, pushing production changes, or releasing a version as part of specification preparation.

## Further Notes

Product scope and search policies are accepted in [ADR-0001](adr/0001-fragment-catalog-search-chain.md). Use [CONTEXT.md](../CONTEXT.md) for domain vocabulary, [SOURCE-CATALOGS.md](SOURCE-CATALOGS.md) for source-specific routes and conditions, and [QUALITY.md](QUALITY.md) for the distinction between local tests, dated live evidence, and editorial acceptance.

This document records the accepted implementation and test scope. Implementation details above follow the current CLI/provider/brief/ledger design and may be refined while preserving the accepted behavior. Implementation status and successful access/acquisition evidence remain separate from specification acceptance.

The selected tracker is GitHub Issues in `kovr33k/get-brolls`, configured in [issue-tracker.md](agents/issue-tracker.md). Published as [GitHub issue #2](https://github.com/kovr33k/get-brolls/issues/2) with `ready-for-agent`; the issue includes the domain vocabulary and retained source contracts.
