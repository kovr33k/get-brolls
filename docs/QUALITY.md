---
type: documentation
status: current
created: 2026-09-15
updated: 2026-10-19
tags: [get-brolls, quality, qa, evidence]
---

# Qualidade e evidências — GET B-ROLLS 2.16.0

Este documento resume a qualidade atual e os limites das evidências. Relatórios cronológicos, URLs públicas de amostras e resultados de versões anteriores ficam no [arquivo de evidências](archive/quality-evidence-through-2026-10-07.md). Resultados ao vivo são registros datados, não promessa de disponibilidade futura nem aprovação editorial.

## Current integration state

The accepted catalog engineering scope is **complete**: parent [#2](https://github.com/kovr33k/get-brolls/issues/2) and child tickets #3–20 are closed. The current [acceptance checkpoint](CATALOG-ACCEPTANCE.md) maps all eight final criteria to their evidence and records the operational limits separately.

The runtime integration baseline is [PR #42](https://github.com/kovr33k/get-brolls/pull/42), version **2.13.8**, merged at `9cc2d059949224c481939c455c2e79d9e93148e4`. Its [Windows/Python 3.14.4 CI](https://github.com/kovr33k/get-brolls/actions/runs/37544014877) passed **1,250 tests with 26 skips**, together with lint, formatting, types, version/mirror and syntax checks. The saved verification artifact matches the merged runtime tree. Local post-merge verification passed **116 tests with one skip** plus version/mirror, links and frontmatter checks. The skip concerns invalid synthetic video metadata, not the acquired source samples. PR #41 and older checkpoints are historical evidence, not outstanding integration gates.

## Subtitle-language inspection — 2026-10-09 (2.13.9 candidate)

A full local Windows/Python 3.14.4 suite passed **1,273 tests with 30 skips** before the final missing-original-track guard. The final focused rechecks and local tooling results are recorded separately below. Twenty-four new offline tests cover ES/RU/UK/PT/EN selection, original author/automatic captions, regional tags, partial acquisition failures, Unicode scoring and CLI language propagation. This candidate is separate from the integrated 2.13.8 baseline above; its required PR Windows CI remains an integration gate.

After the final guard, **142 inspection/regression tests with one skip** passed. The logging restoration passed **112 logging tests with four skips**. A subsequent full run exercised **1,274 tests with 30 skips**, with one `WinError 10053` connection-abort error in the unchanged `test_serve` missing-token refusal test. The entire server module then passed **33 tests with two skips**, without source changes; both the failure and retry are retained, and the cause is not established. Combined passing results cover the final suite; this is not a claim of a single completely green full run on the final revision. Final lint, formatting, types, version/mirror and relative-link checks passed; Bash/PowerShell/JavaScript syntax, installer prerequisites and the PowerShell launcher also passed on the same local dependency/configuration state. Local Node was 24.18.1; the maintained CI pins Node 22.

Three bounded YouTube observations with yt-dlp **2026.8.19** obtained original automatic captions and ranked windows using the explicit video/query language. Each selected three-second working clip was acquired, strictly decoded with FFmpeg and viewed as a contact sheet. All three measured **1920×1080**, without upscaling.

| Public source and language | Obtained text | Acquired source interval / measured duration | Viewed contents |
|---|---|---|---|
| [RTVE Noticias eclipse report](https://www.youtube.com/watch?v=7NTeduS9T-o), ES | `es-orig`, 57 cues; query `eclipse solar` | 15.719–18.719 s / 3.00 s | Studio presenter beside Sun graphics; this window is not direct eclipse footage. |
| [Physics sky explanation](https://www.youtube.com/watch?v=Zgo-eG-gZFg), RU | `ru-orig`, 91 cues; query `небо голубое` | 11.880–14.880 s / 3.00 s | Presenter outdoors holding plants under a blue sky. |
| [Suspilne Dnipro planetarium report](https://www.youtube.com/watch?v=RitX7Kd5LsI), UK | `uk-orig`, 58 cues; query `планетарій` | 18.610–21.610 s / 3.04 s | Planetarium exhibit, then an interview at the end of the contact sheet. |

The RU metadata advertised both dubbed English and Russian `*-orig` tracks; declared Russian audio selected `ru-orig`, independent of listing order. Original-author preference and its bounded automatic fallback have offline coverage; these three live samples all used automatic captions. The first contact-sheet attempt used an incorrect output folder in the verification harness; previews were regenerated from the already acquired clips, without another download. Raw failure observations and corrected media/reports are retained outside distribution. These samples establish subtitle acquisition, literal scoring and the recorded preview contents at that date, without operational approval, cleared reuse rights or validation of the narration's claims.

## Numeric motion graphics — 2026-10-13

The [numeric graphics checkpoint](MOTION-GRAPHICS-ACCEPTANCE.md) maps all sixteen criteria of [#53](https://github.com/kovr33k/get-brolls/issues/53) to the public CLI, compatible project records, optional Remotion runtime, immutable renders and shared Storyboard. It records 89 focused checks, actual Full HD H.264/30 fps Windows output and browser observations separately from subsequent approval, delivery and Resolve acceptance. Final integration requires the submitted PR's complete Windows checks. Private project inputs and media remain outside distribution.

## Bounded graphics pilot — 2026-10-14

The [graphics pilot checkpoint](GRAPHICS-PILOT-ACCEPTANCE.md) records six exact current-version visual approvals across five concept types, three narration-backed scene deliveries with separate VO and retained editable sources, and direct human confirmation of all three pairs in Resolve at 30 fps. The other three concepts remain estimated visual drafts. Single-context sequential production replaces delegation as a requirement of this accepted pilot. Older contexts, versions, requests and approvals remain historical records. These statements establish the bounded supplied-material test, not an all-five-concept narration-backed production montage.

Storyboard observations cover per-piece version numbers, one visible piece, cyclic pending navigation, saved decisions and representative video posters without moving the playback clocks. All eight saved versions in the main pilot remained intact; all three delivered source packages and six media files were checked. Private originals, paths and acceptance statements are retained outside distribution. Final integration still requires the associated PR's complete Windows checks and a local post-merge verification; the issue closure records identify that integrated evidence.

## Saved image references — 2026-10-15 (2.14.0 candidate)

Seven synthetic-image HTTP/CLI journeys pass for initial authoring and exact-version revisions, copied PNG/JPEG bytes, reopen/import, immutable reference context, retained history, conflicting prompts and targets, malformed input and missing or changed files. Combined final focused results cover **65 passing tests**: seven reference journeys, 21 graphics-review tests, eleven graphics-media workflow tests, 24 Storyboard tests and two CLI-surface checks. Ruff, formatting, Pyright, version/mirror, relative links and JavaScript syntax pass.

The initial full local Windows run exercised **1,616 tests with 32 skips** and found two failures: the intentional CLI addition needed its golden fixture updated, and an untouched initial graphics row incorrectly made a refused alignment import look successful. Both were corrected and their affected checks pass. A new same-prompt image regression also needed its synthetic source regenerated before reuse; all seven reference tests then passed.

A fresh local post-merge run on `973e7c7` passed **1,617 tests in 609.309 seconds with 32 skips**, with no failures or errors. Global lint, formatting, types, version/mirror, relative links, Bash/PowerShell/JavaScript syntax and whitespace checks also passed. The tested code and dependency files remained unchanged throughout verification. This establishes local technical verification; required PR Windows CI remains a production-publication gate.

Actual local-browser observations cover native file selection, transfer/save and reopened prompts/thumbnails for a planned scene and a complete v1, distinct selected/saved feedback, and mobile layout without horizontal overflow at a 375-pixel viewport. Node regressions additionally cover version-bound image drafts and upload/save refusals without a misleading JSON-media fallback. The reference is independently frozen and excluded from composition media and the editable-delivery binary allowlist. Tests use synthetic files and the fixture renderer; no paid analysis or production render was launched. Reference-matching quality and integrated human visual acceptance remain separate, with final acceptance in [#79](https://github.com/kovr33k/get-brolls/issues/79).

The 2.14.0 delivery was integrated through [PR #80](https://github.com/kovr33k/get-brolls/pull/80), with its required Windows checks passing, and [#75](https://github.com/kovr33k/get-brolls/issues/75) closed. Seven fresh image-reference tests passed locally after the GitHub merge.

## Mixed image/video references — 2026-10-16 (2.15.0 candidate)

**Integrated:** [PR #82](https://github.com/kovr33k/get-brolls/pull/82) merged at `0b17b350b06311e7e9dc3b8978391ae2517cde4e` after [Windows checks](https://github.com/kovr33k/get-brolls/actions/runs/38891227512) passed **1,622 tests, 26 skips**, plus the maintained tooling checks. Fresh local post-merge verification passed all **12 reference tests** and version/mirror checks before branch cleanup. [#76](https://github.com/kovr33k/get-brolls/issues/76) is closed. The following aggregate observations describe the preceding local development evidence.

The complete local Windows unittest collection was exercised in two groups: **267 graphics tests** (one skip) and **1,354 remaining tests** (31 skips). The first remaining-tests invocation had 12 import-path errors in a private grouping script, not product failures; all three affected test modules passed when rerun through the normal unittest entry point. A fifth mixed-reference journey was then added and passed, bringing the exercised collection to **1,622 distinct tests, 32 skips**. Subsequent affected rechecks cover the final reference code and interface. This is aggregate local evidence, not a claim of one uninterrupted full-suite pass or completed PR CI for 2.15.0.

Five mixed-reference HTTP/CLI journeys cover initial and revision requests, duplicate names and stable labels with gaps, save/reopen/import, noninitial source intervals, explicit whole clips longer than one minute, actual decoding and measurements, unsupported/truncated/corrupt MP4, file/count/total bounds, unchanged manifests after refusals, missing/tampered temporal evidence, original-candidate identity, source clocks, approval/use gates, frozen history and editable-delivery exclusions. Seven legacy single-image journeys remain compatible. Node interface checks cover partial-batch failure/retry, retained successful transfers, stable labels after draft removal, changed saved-request identity on reopening, honest preview errors and refusal of misleading JSON-media fallbacks.

Actual local-browser observations cover the native multiple-file picker, two identically named stills plus a video, removing R2 while preserving R3, a saved image/video request, imported prompt/labels, and native playback of the saved MP4 (320×180, six seconds). At a 375-pixel viewport, document and client widths were both 360 pixels, with no horizontal overflow. The temporary viewport was reset. Browser preview failure is covered by the interface regression, separately from successful real playback.

A synthetic native Remotion render, using the installed locked runtime and prepared browser, places the explicitly selected blue **3–5-second** interval under the authored NumericStat panel. The original's first three seconds are red; decoded output pixels and the viewed Full-HD frame confirm the blue interval, independently of a fixture renderer. The selected source and temporal sheet were inspected. An actual editable delivery excluded design-reference originals and retained restricted composition media through the existing separately-held path. Synthetic approvals and permissions apply only to these test fixtures. No paid semantic service, provider generation, real-client visual acceptance or Resolve acceptance was performed. Human reference-matching acceptance remains in [#79](https://github.com/kovr33k/get-brolls/issues/79).

## Active and shared reference instructions — 2026-10-16 (2.16.0 candidate)

The complete local collection exercised **1,628 tests with 32 skips**. Its sole failure expected the former “all graphics” checkbox wording; the prompt-directed scope label intentionally changed. After updating that assertion, the full review module passed **21 tests**, the active/shared-context journeys passed **six**, and Storyboard regressions passed **24**, including the actual JavaScript interface harness. These rechecks cover the final affected behavior. This is aggregate local evidence, not a claim of an uninterrupted green full run or completed PR CI for 2.16.0. Lint, formatting, types, CLI-surface, version/mirror, JavaScript syntax and relative-link checks passed during development.

Synthetic HTTP/CLI journeys cover text-only reuse of mixed originals and original temporal-inspection identities, individual removal/replacement with equal display names and different hashes, an explicit empty set, immutable old content, stale-base refusal, missing/changed bytes, unchanged explicit composition/source clocks/permissions, shared subsets with retained local exceptions, untouched third-scene approval, fixed handoff targets, later-scene exclusion, retry and visible partial/conflict outcomes. A group remains incomplete until each fixed target has its own valid result.

Actual local-browser observations confirm replacement through the native single-file chooser, retained R3 after removing R1, honest saved/unresolved/incomplete states and both concrete shared targets, and frozen historical files/instructions with editing disabled. At a 375-pixel viewport, document scroll/client widths were both **360 pixels**; the viewport override was reset. A native locked-runtime Remotion follow-up produced a new Full-HD version with the requested changed caption and retained the original blue **3–5-second** background, reference analyses, narration and original version files. The neighboring saved request remained byte-for-byte unchanged. Saving/importing/resolving the shared group did not add a render. All media and decisions were synthetic fixture evidence; no human reference-matching or Resolve acceptance is claimed. Fault-recovery evidence for [#78](https://github.com/kovr33k/get-brolls/issues/78) follows below; integrated human acceptance remains [#79](https://github.com/kovr33k/get-brolls/issues/79).

## Interrupted reference work — 2026-10-16 (2.16.0 candidate)

The final combined active/shared-context and recovery branch completed the local Windows check script: **1,635 tests in 895.506 seconds, with 32 skips and no failures**, plus lint, formatting, types, skill mirror and relative-link checks. Version coherence, JavaScript syntax, documented continuation help and the final 24-test Storyboard recheck also passed. PR CI and integration remain separate requirements.

Seven public HTTP/CLI synthetic-media fault journeys cover initial and revision transfer cutoffs, a valid JSON prefix shorter than its declared body, failure before metadata publication, a durable save with a lost response, session rotation, persistent replay after 35 ordinary saves, writer-lock contention, interrupted import/context/scope journals, committed import with failed page regeneration, fixed shared targets and explicit composition inclusion. Replays retain one submission/request and reuse completed results; a later scene stays outside the fixed group. Changed originals or output bytes report blocked/conflicted work while retaining files. Read-only status is checked under an existing writer lock and against before/after file hashes. An unchanged unknown narration operation retains its state and loopback-provider request counts while scene continuation reuses its result.

The first PR CI ran all 1,635 tests with 26 skips and exposed one test-only mismatch between Windows short and long path spellings for the same saved submission. A focused Windows-alias reproduction confirmed that the file and durable name were unchanged. The replay regression compares actual file identity and the stable name rather than requiring identical path spelling; no runtime behavior was relaxed. The required PR check remains authoritative for the corrected final revision.

An actual local-browser fault harness disconnected the first successful save response after durable publication. The page retained the draft and reported an unconfirmed save; retry returned the same stable JSON filename. Import and replay added exactly one graphics request and kept the two existing versions. Request-bound continuation also verified and reused the previously rendered native Remotion **v2**, with no new render, repair or paid submission. The harness is private test tooling; production has no fault-injection option. All originals, permissions and editorial decisions here are synthetic fixtures. This evidence does not replace final PR Windows checks, human reference-matching or Resolve acceptance.

## Integrated reference acceptance preparation — 2026-10-16 (2.16.0 candidate)

The [reference acceptance checkpoint](GRAPHICS-REFERENCES-ACCEPTANCE.md) maps all 55 stories and 13 parent criteria to automated, browser/native and human evidence. A fresh synthetic project retains three unapproved native Full-HD previews: image-guided initial production, an exact-version mixed-reference revision with the actual blue original **3–5-second** background, and a text-only descendant retaining both references and original data/narration. All three are H.264, 30 fps and two seconds, strictly decoded and measured. Their originals, prompts, analysis limitations, temporal sheet and old-version hashes are retained outside distribution.

The still is an authored geometric palette/layout sketch; the selected video interval is flat blue without audio or fine motion. This demonstrates the stated source-clock/inclusion and retained-direction behavior, not general cinematic style matching. There is no recorded VO in this packet. The existing audio/paired-media and bounded Resolve evidence retains its original scope. These synthetic previews remain technical evidence without human visual approval. The later real-project assessment and amended acceptance gate are recorded below; final integration remains separate. Required PR Windows checks apply to the revision being integrated; separate AI-module work is not represented as an already tested combined release.

## Reference visual acceptance and amended scope — 2026-10-18 (2.16.0 candidate)

A separate real project received exact-version chat approvals for an image-guided draft v2 and a text-only revision v3. The follow-up retained the original image/analysis basis, narration text and earlier version bytes/history. Both native H.264 previews are 1920×1080, 30 fps and ten seconds; strict decoding and measurements passed. Their timing remains estimated without recorded VO. Private prompts, sources, approval statements and media are retained outside distribution. These approvals concern the displayed drafts, without a factual audit, final delivery or new Resolve observation.

The acceptance scope was explicitly amended to remove an additional human video-reference demonstration. Video upload/persistence, requested intervals, actual inclusion, retained direction, shared scope and recovery remain covered by the existing automated/browser/native evidence. General cinematic video-style correspondence is not claimed as human-accepted. The [checkpoint](GRAPHICS-REFERENCES-ACCEPTANCE.md) preserves this boundary for all 55 stories and 13 criteria.

Required [Windows CI](https://github.com/kovr33k/get-brolls/actions/runs/38971486563) passed for executable revision `7e54263`: **1,635 tests, 26 skips, no failures, 1,245.798 seconds**, plus the maintained tooling checks, with a matching verification tree. The final documentation-only PR revision still requires its own required check before integration. Separate AI-generation changes are outside this evidence.

## Ordered AI sequences — 2026-10-19 (issue #88)

Authenticated Storyboard workflows exercise bounded ordered native and OpenRouter video sets through mocked provider HTTP and real FFmpeg media. Distinguishable colored clips prove placement and order; silent/tonal segments distinguish scene sound from the separate recorded-narration preview. Checks cover exact frame coverage including fractional project FPS, retained originals and trims, independent sequence approval, portable review import, changed recording/first-frame approval, short outputs, explicit paid full-set confirmation, duplicate launches, restart and GET-only retained-handle recovery. Browser fixtures cover explicit launch, separate sequence review/export and preservation of unsent comments. Scope, counts, actual media properties and below-profile readiness remain visible. Final required Windows CI must match the combined submitted tree.

These are synthetic recordings/media and mocked transport, not new provider productions or human editorial acceptance. They do not establish OpenRouter entitlement/spending, live continuity or motion quality, production narration alignment, comprehensive interruption recovery, Resolve delivery or complete-module acceptance. Earlier real Grok evidence remains limited to its separately approved image and six-second video below. Later gates are issues #89–91.

## OpenRouter paid media — 2026-10-19 (issue #87)

Dedicated image/video adapters share durable AI jobs, saved originals, exact human review and GET-only known-video recovery. Storyboard separates preparation from confirmation and displays frozen model, prompt, reference/first-frame identity, recorded interval, sound, output count and estimated or explicitly unknown cost. Subscription actions never select this paid route. Automated checks use synthetic media and mocked HTTP: one/three-image scopes, partial failure, exact first-frame and interval-reference bytes, duplicate/lost responses, changed inputs, revoked approval, download recovery, invalid output, credential/redirect boundaries and read-only refresh. A browser fixture also checks restored confirmation, exact three-output consent and preservation of later drafts. Initial reference validation was corrected to use separate temporary staging, preserving worker write-once filenames.

Official dedicated API documentation and public model metadata were checked on this date; example profiles are described in [GUIDE](GUIDE.md#explicit-paid-openrouter-launches). Public metadata GETs establish the advertised wire/capability contract only. No paid generation, spending, actual OpenRouter account entitlement, real reference fidelity or Resolve use was exercised. Native Grok live evidence below remains bounded to its own route and is not OpenRouter acceptance. Final required Windows checks must cover the submitted revision; complete production acceptance remains issue #91.

## Grok OAuth media — 2026-10-18 (issue #86)

The implemented route follows the fixed Imagine side-call contract in [official grok-build source](https://github.com/xai-org/grok-build/tree/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build). It reads only the installed client's retained xAI OIDC account and actual client version. It does not run a reasoning CLI turn or assert installed streaming-json/ToolOutput parity. Static keys, alternate endpoints, silent model substitution and generation retries are excluded.

One explicitly authorized live image POST returned an original JPEG, 1280×720, through `grok-imagine-image-quality`. After explicit approval of those exact bytes, one video POST through `grok-imagine-video-1.5` returned an MP4: 736×400, 24 fps, 6.041667 seconds, H.264 with AAC audio and an embedded JPEG cover. The cover exposed and reproduced a decoder-validation bug; the corrected validator recovered the retained original without another provider call. Image and video received separate explicit technical approvals. The narration waveform/alignment for this exercise was an identified synthetic timing fixture, not production speech or transcription evidence. These dimensions are below Full HD; there is no Resolve or complete-module acceptance.

Synthetic authenticated Storyboard/CLI coverage exercises the actual OAuth media adapter with mocked HTTP responses: artifact decoding and invalid output, exact first-frame bytes, independent review, missing input, duplicate identities, unknown submit, retained remote identity and retrieval without another POST. Reference-led stills and exact Apply transfer actual frozen PNG/JPEG or requested video-interval frames, with source/sent hashes; spatial/format compression preserves originals. Direct transfer does not claim a separate native analysis or mark guidance inspected. Live reference matching, additional model/profile combinations, complete sequences and delivery remain outside this bounded evidence.

## AI stills — 2026-10-16 (issue #83)

This dated entry describes the earlier GPT/refusal implementation. Its Grok transport limits are superseded by the 2026-10-18 entry above.

Local public-workflow coverage for economy scene choice and one GPT-subscription still uses a synthetic `codex app-server` transport, synthetic PNG/JPEG and the authenticated loopback Storyboard. That establishes routing, three alternatives, frozen jobs, duplicate request identity, unknown-submit refusal, decoded hashes and exact-still review. It does not establish ChatGPT account entitlement, actual `savedPath` media from a live login, image quality or Resolve acceptance. Those remain a separately authorized pilot.

Three-image comparison reuses that synthetic transport for an explicit three-output launch. Prompt-distinct PNG bytes, partial failure, unknown submit, and Storyboard slot selection are part of the same public CLI/HTTP contract. Current local synthetic checks are recorded in the AI reference revisions entry below. Native Grok image and video are not established: installed streaming-json starts at `tool_call` `pending`, the native session folder and `ToolOutput` shape are not proven equal to the public grok-build tree, and `--model` does not prove the media model. The adapter therefore returns unverified and does not start a process. Caller-supplied account JSON is not entitlement.

Public timing and video workflow tests are synthetic. They use a planted completed analysis, decodable WAV/PNG/MP4 fixtures, and a test-only patch around the refusal point. That public workflow covers explicit timing, bounded preview reuse, clip-bound review, and a frozen video request. It does not establish native media entitlement, installed tool output, or a fail-closed one-call guarantee. The native Grok adapter remains unimplemented: it does not start a process or send a request, and no installation has been accepted as capable. The pre-tool hook fails open on transport, timeout, malformed, ask, and unknown results, so a callback denial alone is not that guarantee. Current local synthetic checks are recorded below.

## AI reference revisions — 2026-10-18 (issue #85)

The focused AI run passes **138 tests with one skip**, including eleven actual loopback HTTP journeys. Synthetic PNG/JPEG/MP4 and the test app-server cover received bytes and hashes, authenticated private previews, Host/Origin/session refusals, malformed inputs, interruption/retry, initial/revision targets, replacement/removal, late video intervals named in ordinary instructions, explicitly shared reference guidance, bound observations and frozen history. The comparison Apply result keeps separate progress/media beside the three retained slots. Node checks cover repeated clicks, late responses, unsent files/drafts, changed targets and reopening exact economy/comparison revisions. These counts overlap the full suite and must not be added to it.

Before combining the AI branch with PR #92, the full local Windows run passed **1,756 tests in 933.881 seconds with 33 skips**, without failures or errors. Global lint, formatting, types, skill mirror, relative links and both Storyboard JavaScript syntax checks passed. Verification input hashes matched at completion. This evidence predates the combined branch; final verification must use the combined revision's Windows checks.

Actual local-browser observations cover native PNG file selection and transfer, replacement before the first still, saved shared-style context on other AI cards, first synthetic production with saved guidance, exact-still Apply, beat-guidance Remove, retained text on another scene and restoration of the selected economy revision after reopening. The observed 497-pixel viewport has no horizontal overflow. This is a synthetic media/transport exercise; actual GPT reference matching, account entitlement, Grok/OpenRouter production and Resolve acceptance remain the separately authorized provider/Resolve pilot in issue #91.

The broader regression initially found two tests that searched the entire inline HTML/JavaScript for the word `autoplay`, including assignments that disable it. Their corrected checks parse audio/video attributes; a separate regression rejects both `autoplay` and `autoplay="false"`. The two affected public media workflows and that check pass together.

## Combined AI and Storyboard reference workflows — 2026-10-18

The AI branch includes `origin/main` at the [PR #92 merge](https://github.com/kovr33k/get-brolls/pull/92), `d67439b`. Three synthetic mixed-project journeys exercise one authenticated server with both reference upload configurations, joint review import, exact AI/Remotion versions, frozen earlier bytes, independent lost-response retries, restart/reopen, and request-bound graphics continuation without another image generation or render. Incomplete AI JSON and duplicate Content-Length or Transfer-Encoding framing are refused before a saved reference or selection can change. The complete final Windows verification is run on the combined branch; older separate-branch counts above do not establish that result. Actual provider and Resolve acceptance retain their previous scope.

The combined focused run passes **246 tests in 368.600 seconds with three skips**. It includes all AI modules, the three new integration journeys, single/mixed/active reference and recovery journeys, graphics review, the HTTP server, Storyboard JavaScript harnesses and CLI-surface compatibility. These counts overlap the final complete suite and are not added to it.

## What each evidence layer establishes

| Evidence | Establishes | Does not establish |
|---|---|---|
| Offline mocks and synthetic media | Contract behavior, budgets, recovery, compatibility and regressions | Live account/session access or actual footage availability |
| Bounded dated source observation | The recorded search, card, locator or access failure at that time | Universal or future source availability |
| Acquired representation and strict decoding | Those bytes, their measured dimensions/duration and successful decoding | Editorial fit, cleared original quality or reuse rights |
| Viewed suitability confirmation | The recorded preview/file matches the stated fragment under its current signature | Operational approval or factual validation of the narration |
| Explicit human decision and reuse conditions | The recorded decision and conditions for that particular candidate | Approval of another file, changed interval or unrelated source |

`preview` may obtain working media before an editorial decision. Final fetch/delivery still depends on operational approval and recorded reuse conditions. Configuration presence, `doctor` and installer prerequisite checks do not replace source acquisition evidence.

## Current real-review and print evidence

The representative scenario preserves eight original Spanish fragments and eleven hashed, decoded previews from six source routes. Six viewed options qualify and five remain unsuitable; no fragment reaches three options. The existing search chains remain resumable. Actual exhausted/access-limited shortfalls and stop-at-three behavior have separate dated source and audited offline evidence. This is a bounded acceptance scenario, not a completed montage or validation of the narration's claims.

Eight Approve and three Reject choices remain **test evidence**, with all eleven signatures/epochs verified. They have not been imported as operational approvals, and no real delivery was made. This scope is recorded in the evidence; ordinary review exports do not enforce it with a dedicated test-only marker. Common approval/rights/fetch/verification/delivery compatibility is independently covered by synthetic regressions. No additional blanket sign-off or unrelated licensed-photo delivery is required to close the engineering scope.

The real Storyboard passed navigation, source/narration switching, the search-options journal and the mobile overflow/image check. The corrected print-engine PDF has eleven pages with all eleven images; every page was rendered and visually inspected for source links, narration, intervals, decisions and layout. The supplied earlier PDF omitted two images and remains a preserved failure observation. The delayed-image reproduction, executable regression and corrected result are recorded in the [dated print report](archive/quality-evidence-through-2026-10-07.md#integrated-review-and-print-reconciliation--2026-10-07-2138).

## Current source limits

- LoC native JSON access remains unverified after HTTP 403. The supplied 5880×3049 TIFF master is separately acquired, decoded and linked; it does not establish API access.
- GDELT's selected original remains restricted. UN Web TV's decoded 1280×720 working window does not clear a full editing original. UN archive original requests/licensing and Destockd's unknown exact source-film cut boundaries remain explicit.
- Europeana's acquired institution image retains conflicting item/resource rights and unknown master quality. EC fallback/HLS acquisition has offline coverage, not a new live success claim.
- Required X/Grok OAuth has bounded native search evidence for the exercised model/tool pair. Separate manual-media acquisition does not implement automatic remote X media fetching, and no billing/model fallback is allowed.
- Browser/account routes still depend on the actual session, whitelist, geography and item. Instagram/TikTok are bounded browser/URL workflows, not global CLI keyword-search APIs. Missing standalone Playwright CLI diagnostics remain separate from observed integrated-browser use.
- Rights, operational decisions and factual suitability remain independent. Stock is explicit. The requested-original counting policy remains deferred under [ADR-0001](adr/0001-fragment-catalog-search-chain.md).

The [source reference](SOURCE-CATALOGS.md) describes current capabilities and route requirements; the [operational guide](GUIDE.md) describes execution. Dated access failures must not be turned into permanent platform-unavailability claims.

## Verification policy

Follow [CONTRIBUTING](../CONTRIBUTING.md#desenvolvimento-e-verificação) to reuse evidence that still represents the affected code, dependencies, configuration, artifacts and environment. The complete maintained Windows PR CI must pass for the final revision before integration. Documentation-only changes validate frontmatter, relative links and any affected command examples; they do not require new runtime tests or repeated media acquisition. Required release gates and route-specific real/human checks remain separate.

## Blind tests

A suíte automatizada responde se o programa funciona; o **teste cego** responde se a skill entrega o que promete a um criador de conteúdo. O processo, os papéis (executor cego, juiz com gabarito, amostragem humana), a cadência e o corpus de 16 casos estão em [eval/README.md](../eval/README.md); a pontuação por beat e as metas, em [eval/rubric.md](../eval/rubric.md). É medição editorial, fora do CI de propósito: precisa de rede, sessão e tempo de agente, e todo relatório separa **ambiente** (URL fora do ar, sessão, quota) de **comportamento** (stock sem pedido, licença inventada, aprovação pelo próprio agente).

## Historical evidence index

The [complete quality archive](archive/quality-evidence-through-2026-10-07.md) preserves every prior section, public sample URL, measurement and limitation. Its `pending/open/candidate` statements belong to their original checkpoints and are superseded by the final integration state above.

- [Final print/review reconciliation](archive/quality-evidence-through-2026-10-07.md#integrated-review-and-print-reconciliation--2026-10-07-2138).
- [LoC supplied master](archive/quality-evidence-through-2026-10-07.md#loc-supplied-master--2026-10-06-2136-candidate).
- [Instagram/TikTok browser lifecycles](archive/quality-evidence-through-2026-10-07.md#instagram-and-tiktok-browser-lifecycle--2026-10-06-2135-candidate) and [Instagram two-stream acquisition](archive/quality-evidence-through-2026-10-07.md#instagram-two-stream-acquisition--2026-10-05-2131-candidate).
- [UN archive working preview](archive/quality-evidence-through-2026-10-07.md#un-archive-working-preview--2026-10-06-2134-candidate) and [UN Web TV/Europeana/Destockd reconciliation](archive/quality-evidence-through-2026-10-07.md#remaining-catalog-reconciliation--2026-10-06-2133-candidate).
- [X OAuth and catalog acceptance follow-up](archive/quality-evidence-through-2026-10-07.md#catalog-acceptance-follow-up--2026-10-05-2132-candidate).
- [QA 2.4.0 and the complete blind-test round](archive/quality-evidence-through-2026-10-07.md#qa-da-versão-240--17092026); [earlier blind-test baseline](archive/quality-evidence-through-2026-10-07.md#blind-tests).

Earlier source-ticket closure checkpoints are also preserved in the [acceptance archive](archive/catalog-acceptance-2026-10-07.md). Private projects, media, account material and saved decisions remain outside distribution.
