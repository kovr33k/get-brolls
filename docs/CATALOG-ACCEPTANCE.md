---
type: documentation
status: current
created: 2026-10-05
updated: 2026-10-05
tags: [get-brolls, catalogs, acceptance, evidence]
---

# Catalog integration acceptance checkpoint

This checklist tracks [issue #20](https://github.com/kovr33k/get-brolls/issues/20) and the remaining source tickets against the [accepted specification](SPEC-CATALOG-INTEGRATION.md). It is an acceptance checkpoint, not a completion statement or a replacement specification. Source implementation, dated access/media observations, visual suitability, human approval and reuse conditions remain separate. Detailed public sample URLs and measured outcomes live in [QUALITY.md](QUALITY.md); private projects, media and access material stay outside distribution.

## Source evidence and remaining checks

The current integration batch closes the reconciled implementation tickets #8–12 only after its required Windows PR checks and merge. LoC #7 stays open for acquired-original access and preview; #13–20 and parent #2 are not completed by this batch. Native X discovery and common review fixes are included as tested implementation work, without claiming completion of those remaining acceptance tickets. Production tagging and personal installation are separate from merging this batch.

All twenty retained catalogs remain in the inventory. Required X/Grok OAuth now has bounded CLI discovery and separately observed original/manual-media evidence; final review and acceptance remain open. TikTok live work is paused; its existing URL/import behavior stays supported, and paused acquisition is not a passed acceptance check. Local import and UNifeed do not increase the catalog count.

| Catalog | Ticket | Existing dated evidence | Remaining acceptance evidence |
|---|---|---|---|
| YouTube | #6, closed | Acquired/decoded 1080p preview on 2026-10-05; earlier HTTP 403 is historical | Representative scenario review, explicit decisions and permitted delivery |
| Wikimedia Commons | #6, closed | Selected public image acquired, decoded and previewed on 2026-10-04 | Scenario-level visual/editorial acceptance remains separate |
| Internet Archive | #3–5, closed | Actual factory file; three viewed distinct windows, stop at three and persisted count | Human scenario decisions and reuse conditions; no automatic approval |
| NASA | #6, closed | Selected image acquisition/decoding and preview on 2026-10-04 | Scenario-level visual/editorial acceptance remains separate |
| Library of Congress | #7 | JSON browser challenge; observed restricted item imported without renewed allowance. On 2026-10-05 the saved card still required on-site access; its linked card stopped at browser security verification | Actual acquired-original access remains explicitly unverified. Fixtures cover the supplied-original route; the ticket allows a separately dated rejected-access outcome, which is not a successful media check |
| DVIDS | #8 | Actual selected 1080p MP4 on 2026-10-04; selected 720p operation press-conference window acquired/viewed/decoded on 2026-10-05 | Read-route, identity/date, bounded-filter and common-gate criteria reconciled below; human decisions and reuse remain open; press conference does not prove operation duration |
| Europeana | #9 | Personal-key Search/Record; actual institution JPEG 899×1280 viewed/acquired, linked to the record and previewed/decoded on 2026-10-05 | Key-type, institution/resource identity and common gates mapped below; conflicting rights and highest-quality original remain unknown; bridge drawing does not serve the Venezuela scenario |
| NARA | #10 | Actual selected JPEG, 3152×4728, previewed/decoded on 2026-10-04 | Read-route, object identity and common-gate criteria reconciled below; the scanned page is unsuitable for a bridge and human/reuse decisions remain open |
| Pexels | #6, closed | Bounded explicit-stock acquisition/preview sample on 2026-10-04 | Keep explicit stock policy; no automatic stock substitution for the scenario |
| Pixabay | #6, closed | Bounded explicit-stock acquisition/preview sample on 2026-10-04 | Keep explicit stock policy; no automatic stock substitution for the scenario |
| Mapillary | #11 | Actual 5660×2830 geographic street image, preview/Storyboard/decode on 2026-10-04; selected identity and access rechecked on 2026-10-05 | Source criteria reconciled below; ready for final batch checks and integration. Nearby streets remain unsuitable for the named square; reuse is unknown |
| Telegram | #12 | Authorized whitelist search; scenario interview, custody still and unsuitable airport/court examples acquired/viewed/decoded on 2026-10-05; selected attachment access rechecked | Source criteria reconciled below; ready for final batch checks and integration. Original authorship, capture time, custody-image authenticity and reuse remain unknown; saved browser choices are test-only |
| GDELT TV | #14 | Caption/time locator and exact Archive linkage; selected files restricted | Actual viewable recording/window or an explicit unavailable-original outcome; text is not visual confirmation |
| X | #15 | Retained OAuth refresh; three planned native queries on configured grok-4.7; two cited references; one original viewed and separate 720×1280 video import/preview/decode on 2026-10-05 | Final-state criteria/CI and human review; excerpts remain unverified search metadata; acquisition is manual and sample-specific; reaction video does not show Maduro in custody |
| EC Audiovisual | #16 | Exact VIDEOSHOT/parent and decode on 2026-10-04; actual 1080p Xi summit shot +002 at 14.92–21.5s viewed in the scenario pilot on 2026-10-05 | Source/cache timing and access gates mapped below; human review and live fallback/HLS remain unverified; summit is archival, not a reaction to the operation |
| UN Web TV | #17 | Recent full-text transcript and actual player metadata on 2026-10-04 | Recorded asset/brief access decision, acquired/decoded window and visual assessment; rights/human approval stay separate |
| UN Audiovisual Library | #18 | Actual archive cards/scripts/request routes; 2015 Putin search/card imported on 2026-10-05 with player error 224003 and no downloadable media | Viewable media/supplied-original linkage when obtainable; failed playback and a request locator do not count as viewed options; no automatic request/licensing/procurement |
| Destockd | #19 | Website shot preview acquired/viewed/decoded and Archive source link on 2026-10-04 | Selected source-film file and independently verified exact boundaries; no undocumented API automation |
| Instagram | #13 | Matching Reel video/audio, measured 1080×1920 merge, full decoding and inspect/preview on 2026-10-05 | Complete prepared Storyboard and visual evidence; human audio-sync judgment and reuse conditions remain separate |
| TikTok | #13 | Canonical URL/browser-import fixtures; dated browser access failure | Live acquisition paused; unresolved scope must be explicit before closing #13 or #20 |

## Shared workflow evidence

### Point 1 reconciliation — #7–10, 2026-10-05

The current source-ticket criteria allow missing prerequisites and rejected access to be recorded as **unverified**. They do not require purchasing licenses or declaring human editorial acceptance for every catalog before implementation closure. Common human approval, reuse and acquisition gates must work and remain independently enforced; synthetic gate tests are distinct from dated actual media observations.

| Ticket | Reconciled contract | Current verification and limit |
|---|---|---|
| #7 LoC | Bounded facets, canonical item/resource/file variants, poster exclusion, restrictions, supplied untimed transcripts, original selection and common review gates | Keyed and browser regression suites pass. Original card requires on-site access; linked card remains at security verification. No acquired-original success claimed |
| #8 DVIDS | Read credentials without upload dependency, bounded filters, asset/file identity, capture versus publication dates, pinned inspection and common gates | Saved original and preview hashes checked; dated 1080p acquisition/decode and separate scenario 720p observation retained. Editorial suitability and reuse are separate |
| #9 Europeana | Confirmed key type, record/institution/resource provenance, distinct views and rights, explicit supplied-original route, common gates | Real institution JPEG re-imported through CLI under a separate test identity and previewed: 899×1280, duration/FPS unknown, source linkage retained, approval pending, rights unknown. Conflicting rights and master quality remain unresolved |
| #10 NARA | Configured read route, bounded requests, distinct digital objects, restrictions, unknown geometry/timing and common gates | Saved selected object and preview hashes checked; dated 3152×4728 acquisition/decode retained. Image suitability and reuse are separate |

This reconciliation found and corrected a local still-import bug: ffprobe's one-frame duration/FPS are no longer stored as capture metadata. The Europeana linked-original regression checks import, preview and closed fetch gates. Earlier project records and test decisions remain historical; the corrected live import uses a separate candidate and preserves existing events. Source tickets remain open pending the coherent batch's final review, Windows PR CI and integration.

### Point 2 reconciliation — #11–12, 2026-10-05

| Ticket | Reconciled contract | Current verification and limit |
|---|---|---|
| #11 Mapillary | Token-based geographic image-only search, required bounded geography, selected representation and sequence/coordinates/capture provenance, unknown fields, duplicate counting and common gates | Current selected-image metadata access passed with the same representation identity. The saved 5660×2830 file hash and preview were checked; the prior decoding/viewing result remains applicable. The street image is unsuitable for Plaza Mayor; no new search or download was needed |
| #12 Telegram | Private session and optional SDK, local login/2FA diagnostics, public whitelist and date bounds, durable query-associated cursor/results, bounded waits, exact message/attachment identity, publication versus capture, common review/access/rights gates | Current authorized access to the saved interview attachment passed with the same identity. Six scenario media hashes and previews match dated decoding evidence. Account fixtures cover restart, interrupted recovery, rate waits and inaccessible channels. The synthetic attachment scenario now verifies refusal without human approval, refusal without permission, and verified fetch after both explicit fixture decisions |

Review of this point found a remaining legacy date-export defect: the card distinguished Telegram publication from capture, but print records still exported the legacy message date as capture. Generated review records now use the same date distinction, and print notes include publication separately. A regression fails on the former export and passes after the correction. All 42 focused account/Storyboard tests pass. Regenerating the real eleven-item board left the manifest and saved eleven test choices unchanged; all six Telegram print records now have unknown capture dates and known publication dates. Browser review still shows eight Approve and three Reject. The native print call prevented further page automation, so rendered PDF acceptance remains unverified.

Both tickets are technically ready for the coherent batch's final review, hosted Windows CI and integration; neither is closed yet. Human test choices do not grant reuse permission or establish the factual claims in the scenario. LoC #7 remains open for actual original access and preview, as agreed separately.

The existing audited CLI and synthetic-media tests provide these seams; their presence alone does not certify the final branch. Reuse passed evidence only while the exercised code, dependencies, configuration, artifacts and relevant environment still match.

DVIDS #8 and NARA #10 were reconciled against their current acceptance criteria on 2026-10-05. [Catalog adapters](../scripts/getbrolls/catalogs.py) and the [private configuration allowlist](../scripts/getbrolls/config.py) implement configured read access, bounded filters, selected real objects/files, canonical provenance and unknown metadata without upload prerequisites. [Keyed-catalog tests](../tests/test_keyed_catalogs.py) cover key/transport failures, credential scrubbing, separate capture/publication dates, multiple-object identity, missing geometry/media, pinned selection and changed context. Its `test_each_catalog_reaches_preview_confirmation_storyboard_with_closed_fetch_gates` exercises both sources through audited synthetic-media review and independent approval/rights gates. Saved dated media samples establish actual acquisition/decoding, while their unsuitable bridge verdicts remain visible. This reconciliation does not create human acceptance, clear reuse conditions or replace final PR CI.

The remaining ticket evidence maps to the following observable checks. This map records implementation/test seams and live limits; it does not declare the tickets accepted or imply every external operation has succeeded.

| Tickets | Source-specific contract and observable checks | Dated evidence limitation |
|---|---|---|
| #7, #9 | [Keyed-catalog tests](../tests/test_keyed_catalogs.py): real LoC resources versus posters/locators, explicit variants and restrictions; Europeana key-type confirmation before network, institution/resource rights, primary versus separate views, supplied local original and shared gates. [Browser-fragment tests](../tests/test_browser_catalog_fragments.py): LoC challenges, durable import/resume, public locators and supplied originals | LoC acquired-original access remains unverified; Europeana proves one institution representation with conflicting rights |
| #11, #12 | [Account-route tests](../tests/test_account_catalogs.py): required real geography, image-only Mapillary identity and duplicate counting; Telegram whitelist/session boundaries, login/2FA errors, bounded periods, publication versus capture, attachment identity, persisted cursor/recovery and short versus long FloodWait | Mapillary nearby imagery does not prove the target square; Telegram repost origin, capture time and authenticity remain unknown |
| #13 | [Browser-fragment tests](../tests/test_browser_catalog_fragments.py), [Instagram recovery](../tests/test_instagram_recovery.py) and [social recovery](../tests/test_social_recovery.py): shared reservations/imports, canonical URLs, matching Reel stream acquisition, private transport, interruption and common review gates | Instagram pairing/acquisition/decoding is observed; human audio synchronization remains unverified. TikTok live acquisition stays paused |
| #14, #16, #17 | [Broadcast tests](../tests/test_broadcast_catalogs.py): GDELT caption/time locators, station coverage and supplied original; EC keyword search, VIDEOSHOT-first fallback, exact parent/representation, HLS confinement and single source/cache offset; UN locale/full-text and older direct assets, transcript/player distinctions and explicit brief-access versus human/rights gates | GDELT originals are restricted; EC fallback/HLS are fixture-only; UN Web TV has metadata/transcript evidence but no acquired/decoded window |
| #15 | [Native OAuth tests](../tests/test_grok_oauth.py) and [account tests](../tests/test_account_catalogs.py): retained OIDC/selected model, refresh/expiry, actual client header, native tool/citations, explicit date/account filters, three queries, durable completed-result recovery and independent manual-media gates | Bounded native search and one separately acquired X sample are observed; no automatic remote media acquisition or catalog-wide entitlement claim |
| #18, #19 | [Browser-fragment tests](../tests/test_browser_catalog_fragments.py): actual UN/Destockd card and locator identities, observed public scripts/requests, deferred previews, supplied originals, Archive linkage and unknown exact original boundaries | UN player failure/request-only access remains explicit; Destockd acquired preview does not establish source-film boundaries. No automatic licensing or procurement |

| Requirement | Existing observable verification seams | Final checkpoint |
|---|---|---|
| Independent fragment plans, query/language limits, catalog transitions, disjoint pass 2, no pass 3, shortfalls and interrupted recovery | [test_search_chains.py](../tests/test_search_chains.py), [test_archive_fragment_search.py](../tests/test_archive_fragment_search.py), [test_existing_catalog_fragments.py](../tests/test_existing_catalog_fragments.py) | Reconcile the complete final-state evidence and any affected changes |
| Viewed suitability, duplicate grouping, same-recording distinct scenes, stop at three and stale confirmations | [test_archive_fragment_search.py](../tests/test_archive_fragment_search.py), [test_search_chains.py](../tests/test_search_chains.py) | Real scenario observations and actual counts; no metadata-only confirmations |
| LoC/DVIDS/Europeana/NARA originals, restrictions, filters and shared gates | [test_keyed_catalogs.py](../tests/test_keyed_catalogs.py), [test_browser_catalog_fragments.py](../tests/test_browser_catalog_fragments.py) | Close source-specific gaps in the table above |
| Account, browser/locator and timed broadcast routes | [test_account_catalogs.py](../tests/test_account_catalogs.py), [test_browser_catalog_fragments.py](../tests/test_browser_catalog_fragments.py), [test_broadcast_catalogs.py](../tests/test_broadcast_catalogs.py) | Keep configured access and dated live observations separate |
| Legacy briefs/manifests, explicit commands, URL/local import, dry-run, serial writes and read-only status | Existing repository CLI, ledger, status and delivery regressions in [tests/](../tests/) | Include these contracts in the final Windows gate; status must not create/recover/lock the project |
| Prepared review, decisions/export/import, mobile/print, rights, fetch/verify/deliver | Existing Storyboard/review/delivery regressions in [tests/](../tests/) | Review actual scenario previews, record explicit human decisions and conditions, and deliver selected material; UI checks match affected behavior |

## Completion checklist for #20

- [ ] Reconcile every source ticket's actual criteria with implementation, tests and separately dated live evidence; keep unresolved/manual/paused operations explicit.
- [ ] Reconcile required X/Grok OAuth implementation, live search/manual-media evidence and final-state checks; local diagnostics remain separate from authenticated tool access and API billing stays unused.
- [ ] Resolve source-access/original gaps without protection bypass, invented timing or automatic procurement.
- [ ] Exercise the selected representative scenario with original narration, actual viewed options and honest shortfalls. Preserve and verify resume state.
- [ ] Obtain human Storyboard decisions, record actual reuse conditions, then exercise fetch, verify and delivery for selected material.
- [ ] Validate canonical skill/mirror, operational/catalog guidance, configuration examples, changelog, affected command help and relative links for the final contents.
- [ ] Ensure installer prerequisites, doctor, complete offline/lint/type/packaging checks and the required Windows Python 3.14.4 PR CI cover the final state. Doctor is diagnostics, not acquisition evidence.
- [ ] Integrate the coherent completion batch through the authorized PR workflow. Close #20 last among child tickets, then reconcile parent #2; production release and personal skill installation remain separate actions.

Historical passes and closed child tickets remain useful evidence, but cannot close a remaining criterion whose route, material or human outcome is still unverified. The requested-original three-option counting question remains deferred under [ADR-0001](adr/0001-fragment-catalog-search-chain.md).

## Representative review scope — 2026-10-05

The replacement pilot keeps the eight original narration fragments and presents eleven prepared items from six source routes. Six qualified visual matches and five unsuitable examples are explicitly recorded; none is a human approval. Seven fragments have previews, the guard fragment has none, and no fragment meets the three-option target. The board exposes dates, origin, selected intervals, rationale and coverage limitations. Reviewing these items assesses their editorial fit and the review flow; it cannot sign off all twenty source integrations or verify the script's factual claims. Actual rights and human decisions are still absent.

The synthetic UI fixture separately exercised navigation, reload, decision/comment/alternative persistence, server save and three-decision CLI import. Mobile overflow was checked. An exported PDF was not inspected. Those fixture decisions never enter the representative project.

**Human test result.** The replacement board subsequently saved eleven explicit browser choices: eight Approve and three Reject, with no comments or alternate URLs. Every candidate signature and review epoch matched the current pilot. The user clarified that these choices should be retained as a test, with the source catalog recorded for each item. They were therefore preserved in a private test report and structured evidence, without importing them as operational approvals. Telegram supplied six previews; DVIDS, Commons, EC, Archive and X supplied one each. The X media uses an explicit local import while retaining X origin; the Archive speech preserves a saved YouTube-upload origin. Test choices do not change existing visual-suitability observations, establish rights or sign off the full delivery.
