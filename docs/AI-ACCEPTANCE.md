---
type: documentation
status: current
created: 2026-10-22
updated: 2026-10-22
tags: [get-brolls, ai, acceptance, evidence]
---

# AI production acceptance

This checkpoint covers [specification #81](https://github.com/kovr33k/get-brolls/issues/81) and child tickets #83–91. Implementation is integrated by [PR #93](https://github.com/kovr33k/get-brolls/pull/93), merge `497a26010cb25fc16934f67bc6615d8a98c2d26f`. The criterion audit reuses the exact-tree Windows results, fresh post-merge checks and preserved live/human records. It makes no new generation or spending request.

## Child-ticket criteria

Criterion numbers follow each ticket's original acceptance checklist, in order. Together they cover **120 criteria**. The listed public journeys exercise the real local server, ledger, media checks and shared handoff with synthetic media and mocked providers; the [dated live and human checkpoint](QUALITY.md#integrated-ai-pilot-and-resolve-acceptance--2026-10-22) establishes account/media/Resolve acceptance separately.

| Ticket | Criteria | Implementation and regression evidence |
|---|---|---|
| [#83](https://github.com/kovr33k/get-brolls/issues/83) | 1–16 | Original-scenario routing, three alternatives, economy selection, frozen GPT job, exact review, safe native retention and read-only refresh: [state](../scripts/getbrolls/ai_state.py), [public workflow](../tests/test_ai_workflow.py), [native results](../tests/test_ai_native_results.py), [Storyboard fixture](../tests/fixtures/storyboard_ai.cjs). |
| [#84](https://github.com/kovr33k/get-brolls/issues/84) | 1–7 | Three retained independent results, partial failure, group identity and selection/approval separation: [comparison journeys](../tests/test_ai_workflow.py), [state guards](../tests/test_ai_state.py), [paid three-output scope](../tests/test_ai_openrouter_public.py). |
| [#85](https://github.com/kovr33k/get-brolls/issues/85) | 1–15 | Exact revision target, actual image/video bytes and requested intervals, bound inspection, active/historical guidance and confined private transfer: [reference HTTP](../tests/test_ai_reference_http.py), [continuity](../tests/test_ai_reference_continuity.py), [inspection bindings](../tests/test_ai_inspection_bindings.py), [guided launches](../tests/test_ai_guided_launches.py). |
| [#86](https://github.com/kovr33k/get-brolls/issues/86) | 1–22 | Retained-account OAuth, no static-key fallback, exact first frame, actual clip metadata, recorded alignment, separate review and stale-input refusal: [Grok adapter](../scripts/getbrolls/ai_grok.py), [native public journeys](../tests/test_ai_grok_public.py), [transport guards](../tests/test_ai_grok_transport.py), [timing journeys](../tests/test_ai_timing_public.py). |
| [#87](https://github.com/kovr33k/get-brolls/issues/87) | 1–17 | Advertised endpoint capabilities, matching per-launch confirmation, exact reference/first-frame inputs, unknown pricing, private retrieval and no resubmission: [OpenRouter adapter](../scripts/getbrolls/ai_openrouter.py), [public journeys](../tests/test_ai_openrouter_public.py), [transport guards](../tests/test_ai_openrouter_transport.py). |
| [#88](https://github.com/kovr33k/get-brolls/issues/88) | 1–9 | Bounded ordered plans, independently approved first frames, actual frame coverage, trims, scene sound/separate VO and exact sequence review: [sequence production](../scripts/getbrolls/ai_sequences.py), [public sequence journeys](../tests/test_ai_sequences_public.py). |
| [#89](https://github.com/kovr33k/get-brolls/issues/89) | 1–16 | Durable local/remote recovery, unknown-submit quarantine, fault boundaries, worker exclusion and one correction per original operation, including paid re-confirmation: [recovery guards](../scripts/getbrolls/ai_recovery.py), [public recovery journeys](../tests/test_ai_recovery_public.py). |
| [#90](https://github.com/kovr33k/get-brolls/issues/90) | 1–8 | Exact applicable review/use/quality, protected shared packages, retained originals, timing/provenance, separate VO and mixed-project behavior: [AI delivery](../scripts/getbrolls/ai_delivery.py), [public handoff journeys](../tests/test_ai_delivery_public.py), [combined references](../tests/test_ai_graphics_reference_integration.py). |
| [#91](https://github.com/kovr33k/get-brolls/issues/91) | 1–10 | Separately authorized native GPT and Grok plus paid OpenRouter media, real prompt/image/video-reference revisions, same-result download recovery, actual recorded multi-clip coverage and explicit editor/Resolve report: [dated evidence and limits](QUALITY.md#integrated-ai-pilot-and-resolve-acceptance--2026-10-22). |

## Parent user stories

All **60 stories** are accounted for. The implementation-decision sections retain the same boundaries: the managing agent supplies scenario routing; shared project state, locks/journal, review, narration and delivery remain authoritative. Transport details stay behind the common production model. Existing source/catalog and graphics contracts retain their full regression coverage.

| Stories | Accepted behavior | Child coverage |
|---|---|---|
| 1–13 | Original routing, generated-asset identification, three treatments, economy/comparison modes, independent selection/comment and shared style/references | #83–85 |
| 14–18 | Exact still review, approved animation input, additional first-frame review and separate still/video decisions before narration | #83, #86, #88 |
| 19–26 | Actual recording/alignment, complete ordered coverage, paired preview, separate VO and explicitly requested sound | #86–88, #90 |
| 27–36 | Ordinary prompt revisions, actual image/video guidance and requested intervals, ambiguity refusal, retained context/targets/history | #85 |
| 37–42 | Direct Storyboard actions, in-place progress/errors, retained beat/drafts/files, no implicit production and collapsed diagnostics | #83–85, #89 |
| 43–48 | Subscription preference, capability/auth/quota states, no billing fallback and matching paid scope/estimate/correction confirmation | #83, #86, #87, #89 |
| 49–54 | One correction, preserved attempts, stable/frozen identities, same-result recovery and visible uncertain submissions | #83, #89 |
| 55–57 | Affected-only invalidation, retained unrelated beats and honest output/profile measurements | #85, #86, #88, #90 |
| 58–60 | Shared Resolve handoff, portable review and reusable provider/beat/job/review/delivery boundaries | #83, #86–90 |

## Parent behavior coverage

The parent defines **16 behavior-coverage cases**. Their acceptance boundary remains editor-visible actions → durable project/media → shared delivery.

| Case | Evidence |
|---|---|
| 1: original routing and other visual routes | State/public workflow and combined AI/graphics-reference journeys |
| 2: economy, explicit three-image comparison and retained alternatives | Comparison public journeys and Storyboard fixture |
| 3: exact approval before animation | State, Grok and OpenRouter first-frame/revocation tests |
| 4: recorded timing and multi-clip coverage | Public timing and ordered-sequence journeys; actual two-clip pilot |
| 5: prompt/image/video revisions and retained context | Reference HTTP, continuity and inspection/guided-launch journeys; actual three-edit pilot |
| 6: direct UI actions, progress and retained drafts/files | Storyboard interaction fixture plus dated live browser observations |
| 7: matching paid confirmation and no billing fallback | OpenRouter public/transport and paid-correction tests |
| 8: duplicate/restart identities and actual media completion | Workflow, native-result, core and recovery tests |
| 9: unknown quarantine and GET-only known-result retrieval | Recovery journeys and actual interrupted OpenRouter download |
| 10: persistent single-correction allowance | Public recovery/correction journeys across restart and comparison/sequence operations |
| 11: affected-only invalidation | Reference continuity, timing and shared delivery journeys |
| 12: actual decoding/metadata, profile shortfalls and separate VO | Native/API media fixtures, live originals and explicit human sound review |
| 13: authenticated/confined server boundary | Reference HTTP, mixed-protocol and committed-media serving guards |
| 14: portable review with live actions disabled | Portable still/sequence import/export and Storyboard fixture |
| 15: protected shared handoff | Handoff integrity, destination conflict, idempotence, history and mixed-project tests |
| 16: source/graphics/narration/CLI/status/journal compatibility | Full required Windows suite and fresh mixed-reference/handoff checks |

## Verification and live acceptance

[Final implementation Windows CI](https://github.com/kovr33k/get-brolls/actions/runs/39701231290) passed **1,905 tests with 26 skips**, with a Windows/Python 3.14.4 artifact for tree `9cd33e4262359bc6f29f56d7fa7aff44e45a7ca4`. The actual merge tree is identical. Fresh local checks of merge `497a260` passed **21 tests without skips** and the Storyboard JavaScript fixture; all seven delivered test-package hashes still match. These overlapping counts are not additive. Acceptance-document follow-ups also require their own final PR checks.

The dated live checkpoint separates native GPT image generation/inspection/revisions, native Grok media, confirmed OpenRouter image/video generation and same-result recovery, actual Inworld alignment, and human/Resolve use. Private original media, exact authorizations, attempt history and the human report remain outside distribution. Automated fixtures establish software contracts; they do not substitute for those live/human observations.

## Accepted capability and quality boundaries

The editor accepted the real low-resolution technical pilot and the policy allowing an explicit quality exception for the exact version and project profile. Measured originals, `native_full_hd: false` and accepted-shortfall warnings remain intact. That test acceptance does not establish native Full HD or broader publication permission.

GPT subscription video and universal raw video-reference production are not claimed. Video guidance uses the actual requested interval and supported derived images. OpenRouter reference transfer is conditional on advertised endpoint capacity; its frozen-byte/interval behavior has synthetic coverage, while general live reference fidelity is unverified. The completed paid pilot used its explicitly approved image/video scopes.

Three older asynchronous STT submissions remain unknown, preserving potentially accepted/charged outcomes and the documented early-response error-reporting limitation. The successful recorded alignment used synchronous STT and a separately confirmed retry. The pilot verifies the selected phrase rather than alignment of the entire supplied script or all recordings. OAuth quota/cost remains unknown and completed authorizations grant no future generation.
