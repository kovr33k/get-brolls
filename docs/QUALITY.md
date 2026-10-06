---
type: documentation
status: current
created: 2026-09-15
updated: 2026-10-07
tags: [get-brolls, quality, qa, evidence]
---

# Qualidade e evidências — GET B-ROLLS 2.13.8

Este documento resume a qualidade atual e os limites das evidências. Relatórios cronológicos, URLs públicas de amostras e resultados de versões anteriores ficam no [arquivo de evidências](archive/quality-evidence-through-2026-10-07.md). Resultados ao vivo são registros datados, não promessa de disponibilidade futura nem aprovação editorial.

## Current integration state

The accepted catalog engineering scope is **complete**: parent [#2](https://github.com/kovr33k/get-brolls/issues/2) and child tickets #3–20 are closed. The current [acceptance checkpoint](CATALOG-ACCEPTANCE.md) maps all eight final criteria to their evidence and records the operational limits separately.

The runtime integration baseline is [PR #42](https://github.com/kovr33k/get-brolls/pull/42), version **2.13.8**, merged at `9cc2d059949224c481939c455c2e79d9e93148e4`. Its [Windows/Python 3.14.4 CI](https://github.com/kovr33k/get-brolls/actions/runs/37544014877) passed **1,250 tests with 26 skips**, together with lint, formatting, types, version/mirror and syntax checks. The saved verification artifact matches the merged runtime tree. Local post-merge verification passed **116 tests with one skip** plus version/mirror, links and frontmatter checks. The skip concerns invalid synthetic video metadata, not the acquired source samples. PR #41 and older checkpoints are historical evidence, not outstanding integration gates.

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
