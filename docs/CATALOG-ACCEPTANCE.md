---
type: documentation
status: current
created: 2026-10-05
updated: 2026-10-07
tags: [get-brolls, catalogs, acceptance, evidence]
---

# Catalog integration acceptance checkpoint

The [accepted catalog specification](SPEC-CATALOG-INTEGRATION.md) is complete for its engineering scope: parent [#2](https://github.com/kovr33k/get-brolls/issues/2) and all eighteen child tickets #3–20 are **closed**. This page records the final acceptance state as of 2026-10-07. Source access, acquired media, visual suitability, operational approval and reuse conditions remain separate facts.

## Final integration evidence

[PR #42](https://github.com/kovr33k/get-brolls/pull/42) completed the review/print correction and final reconciliation in version **2.13.8**, merged at `9cc2d059949224c481939c455c2e79d9e93148e4`. Its [required Windows CI](https://github.com/kovr33k/get-brolls/actions/runs/37544014877) ran **1,250 tests with 26 skips** on Python 3.14.4 and passed lint, formatting, types, version/mirror and syntax checks. The saved CI verification artifact's tested tree matches the runtime integration tree. Focused local post-merge verification ran **116 tests with one skip**, then passed version/mirror, links and frontmatter checks. The local skip concerns invalid synthetic video metadata; it is not a failed acquired-media lifecycle.

[#20](https://github.com/kovr33k/get-brolls/issues/20#issuecomment-6027122097) records all eight completed criteria and post-merge evidence. [Parent #2](https://github.com/kovr33k/get-brolls/issues/2#issuecomment-6027122818) records the resulting closure. Earlier PRs and intermediate closure gates are retained in the [dated acceptance archive](archive/catalog-acceptance-2026-10-07.md), not used as outstanding work here.

## Accepted criteria

| #20 criterion | Completed evidence | Scope preserved |
|---|---|---|
| Twenty catalogs and truthful capabilities | [Source inventory](SOURCE-CATALOGS.md), provider-family contracts and dated source observations | Exactly twenty; local import and UNifeed are not extra catalogs; Coverr/Unsplash stay excluded |
| Fragment search behavior | Audited [search-chain](../tests/test_search_chains.py), [Archive-fragment](../tests/test_archive_fragment_search.py) and provider-family scenarios | Independent fragments, budgets, duplicates, transitions, two passes, stop at three, shortfalls and recovery; no invented results or third pass |
| Compatibility and common workflow | CLI, ledger, read-only status, review, approval, rights and [delivery regressions](../tests/test_delivery.py) in final CI | Synthetic delivery compatibility does not grant real-media approval |
| Bounded real routes and media | Dated access observations, acquired pixels and strict decoding where available | Access failures and manual operations remain explicit |
| Representative real-preview review | Eight original narration fragments, eleven viewed previews, current signatures/epochs and saved eight/three test decisions | Existing review satisfies the criterion; no extra blanket sign-off or unrelated photo approval |
| Guidance and scope | Canonical skill/mirror, operational/catalog documentation, configuration, changelog, command help and links | The managing agent retains planning responsibility; stock remains explicit |
| Prerequisites and final quality gates | Installer prerequisites, doctor, PR #42 Windows CI, matching tested tree and local post-merge checks | Doctor reports availability; it is not acquisition evidence |
| Limits and deferred policy | Explicit restrictions below and [ADR-0001](adr/0001-fragment-catalog-search-chain.md) | No silent source exclusion, procurement, auto-approval or new requested-original counting policy |

## Representative review and print result

The unchanged scenario contains eight original Spanish narration fragments and eleven hashed, decoded media previews from six source routes: Telegram (six), DVIDS, Commons, EC, Archive and X (one each). The X sample enters through explicit local import with X origin retained; the Archive sample retains its saved YouTube-upload origin. Six viewed options qualify visually and five examples remain unsuitable. Seven fragments have previews, one has none, and none reaches the three-option target. The scenario's chains remain **resumable**. Separate dated source checks and audited offline scenarios cover actual exhausted/access-limited shortfalls and stopping at three; this pilot is not a completed montage or verification of its factual claims.

Eight Approve and three Reject choices are preserved **as test evidence**, with all eleven candidate signatures and review epochs current. They have not been imported as operational approvals; the scenario has zero operational approvals and no real delivery. This test scope is recorded in the acceptance evidence, not enforced by a dedicated marker in the ordinary review-export format. Real footage still needs an explicit operational decision, recorded reuse conditions and the common fetch/verification gates.

The real board passed next/previous navigation, selection, source/narration switching, the search-options journal and the 390×844 mobile overflow/image check. The corrected print-engine PDF has **eleven pages and all eleven images**; every page was rendered and inspected for sources, original narration, intervals, decisions, clipping and overlap. Regenerating review preserves the manifest hash. The originally supplied PDF's two missing images and the delayed-image reproduction are retained in the [print evidence archive](archive/quality-evidence-through-2026-10-07.md#integrated-review-and-print-reconciliation--2026-10-07-2138); they are not reported as successful export evidence.

## Current operational limits

- **LoC:** native JSON access remains unverified after HTTP 403. The known-card/supplied-master route separately acquired and decoded the 5880×3049 TIFF; browser viewing does not grant API clearance.
- **Broadcast/archive media:** GDELT's selected original remains restricted. UN Web TV has a decoded 1280×720 working window, not a cleared full editing original. UN archive originals still require their request/license route. Destockd's preview and linked source film do not establish the preview's exact source-film boundaries.
- **Europeana:** the acquired institution JPEG is separate evidence from conflicting item/resource rights and unknown master quality.
- **X/Grok:** retained OAuth and the exercised model/tool pair remain required; there is no API-billing or model fallback. The separate manual-media sample does not implement automatic remote X media acquisition.
- **Browser/account routes:** credentials, sessions, geography, whitelist and individual asset access still apply. Instagram/TikTok use bounded browser/URL workflows; the CLI does not claim global keyword search for them. A dated success does not promise future access.
- **Editorial and delivery:** saved test choices do not establish rights or factual suitability. The extra licensed-photo delivery experiment remains optional, unapproved and undelivered; it is not an engineering closure gate. Requested-original three-option counting remains deferred under ADR-0001.

## Evidence references

Use [SOURCE-CATALOGS](SOURCE-CATALOGS.md) to choose a route and [GUIDE](GUIDE.md) for its commands. [QUALITY](QUALITY.md) summarizes the current evidence and validation boundaries. Complete earlier checkpoints, metrics and public sample URLs remain in the [acceptance archive](archive/catalog-acceptance-2026-10-07.md) and [quality evidence archive](archive/quality-evidence-through-2026-10-07.md). Their historical `pending/open/candidate` wording is superseded by this final state; their dated technical observations and limits remain preserved.
