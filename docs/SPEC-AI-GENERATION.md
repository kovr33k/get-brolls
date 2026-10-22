---
type: specification
status: accepted
created: 2026-10-16
updated: 2026-10-16
tags: [get-brolls, ai-generation, storyboard, narration, integration]
issue: https://github.com/kovr33k/get-brolls/issues/81
---

# AI scene production for narrative beats

The product scope and primary testing boundary were accepted on 2026-10-16. Specification acceptance/publication does not start implementation, dispatch an agent or authorize generation or spending.

## Problem Statement

An editor needs illustrative images and video for scenario passages that benefit from generated visuals. Source-based B-roll and authored Remotion graphics already belong to the project workflow; AI production needs its own coherent path in the same Storyboard.

The editor needs meaningful scene choices, control over the exact image that becomes video, ordinary-language revisions and coverage timed to recorded narration. Moving between chat, generation services and manually refreshed pages breaks that workflow. Unclear billing, duplicate submissions and approvals carried over to changed media make it unreliable.

## Solution

The managing agent analyzes the original scenario into narrative beats and proposes source-based B-roll, Remotion graphics or AI production for the appropriate visual tasks. AI can be an independent editorial approach without an unsuccessful catalog search first. Generated assets remain explicitly identified as generated.

Every AI beat receives three distinct scene alternatives. **AI economy mode is the default:** three textual descriptions, selection with an optional comment, then one generated image for the chosen alternative. Optional **AI image comparison mode** generates three images for visual selection. Both modes use the agreed project AI visual style and output-quality expectations.

The production path is selected treatment → generated still → explicit approval of that exact still → video from the approved still → review of the resulting AI sequence. Stills can be prepared before narration is recorded. Video waits for actual recorded-narration timing and covers the intended interval with several ordered clips when necessary.

Generation, prompt-based revision and animation launch from the Storyboard. Optional image/video references guide the change. Progress and results update without manual reload, preserving the selected beat and unsent edits/files. Earlier versions remain available.

Suitable GPT/Grok subscription routes are preferred. OpenRouter API generation requires confirmation of every concrete paid launch in the Storyboard. Capability/access limitations and uncertain submission outcomes remain visible; none authorizes a paid fallback.

## User Stories

1. As an editor, I want narrative beats planned from my original scenario, so that visual production follows its meaning.
2. As an editor, I want the agent to explain which beats belong to B-roll, Remotion graphics or AI, so that I can understand and correct the proposed treatment.
3. As an editor, I want AI proposed when it serves the visual purpose, so that irrelevant footage searches are not a prerequisite.
4. As an editor, I want generated assets clearly identified, so that an illustration is not mistaken for documentary evidence.
5. As an editor, I want three meaningfully different scene alternatives per AI beat, so that I have a real editorial choice.
6. As an editor, I want economy mode enabled initially, so that reviewing proposals does not generate three images for every beat by default.
7. As an editor, I want to choose one description and generate its image, so that generation follows my selected treatment.
8. As an editor, I want an optional three-image comparison mode, so that I can compare treatments visually when useful.
9. As an editor, I want economy mode to change the comparison format only, so that it does not silently lower quality or change billing route.
10. As an editor, I want to comment on a selected alternative before generation, so that its first image incorporates my direction.
11. As an editor, I want to advance a selected beat independently, so that unfinished choices elsewhere do not block it.
12. As an editor, I want a shared AI visual style proposed for my correction, so that generated scenes fit the project.
13. As an editor, I want optional style references, so that I can communicate appearance more precisely.
14. As an editor, I want to inspect the actual still before approval, so that selecting a description cannot approve unseen media.
15. As an editor, I want animation bound to the exact approved still, so that its visual starting point cannot silently change.
16. As an editor, I want additional starting images approved before animation, so that choosing a treatment does not authorize unseen images.
17. As an editor, I want still and video approvals kept distinct, so that accepting an image does not accept its eventual motion or sound.
18. As an editor, I want to prepare and approve stills before recording narration, so that useful visual preparation can proceed early.
19. As an editor, I want video generated after narration is recorded, so that duration follows the actual passage.
20. As an editor, I want unresolved or ambiguous narration alignment visible, so that a guessed interval is not treated as ready.
21. As an editor, I want full visual coverage for the intended interval, so that I receive a usable sequence rather than disconnected short outputs.
22. As an editor, I want clip order and placement retained, so that the sequence corresponds to the intended passage.
23. As an editor, I want sequence preview with its narration interval and scene sound, so that I can judge them together.
24. As an editor, I want narration separate from delivered clip audio, so that I can mix and edit it in Resolve.
25. As an editor, I want suitable atmosphere and effects where useful, so that scenes can sound natural.
26. As an editor, I want music and speech only when explicitly requested, so that sound respects my direction.
27. As an editor, I want to request a correction or a different scene in an ordinary prompt, so that I do not choose routine technical editing mechanics.
28. As an editor, I want prompt-only revisions, so that attaching a file is optional.
29. As an editor, I want image references, so that I can specify appearance, content or composition.
30. As an editor, I want video references in the first version, so that I can communicate movement and camera behavior.
31. As an editor, I want the requested reference interval inspected, so that production follows the relevant moment rather than an arbitrary opening excerpt.
32. As an editor, I want material reference ambiguity clarified, so that an arbitrary interpretation does not become an unnoticed decision.
33. As an editor, I want references used for their stated purpose and supported operations, so that a style reference is not mistaken for an approved animation input.
34. As an editor, I want active references and unrelated instructions retained until replaced or canceled, so that a revision does not erase earlier direction.
35. As an editor, I want a revision bound to the exact displayed version, so that a new background result cannot silently become its target.
36. As an editor, I want earlier versions and their original context retained, so that I can compare results and understand changes.
37. As an editor, I want generation, Apply and animation in the Storyboard, so that follow-up work needs no subsequent chat command.
38. As an editor, I want progress, results and errors to appear automatically, so that I do not reload the page.
39. As an editor, I want the selected beat and unsent prompts/files preserved during updates, so that background work does not destroy my draft.
40. As an editor, I want browsing, typing, selection and file choice to start no generation, so that only an explicit launch starts production.
41. As an editor, I want a compact main review surface, so that alternatives, prompts, references, results and next actions remain understandable.
42. As an editor, I want diagnostics and provenance in collapsed Details, so that I can inspect them without cluttering review.
43. As an editor, I want suitable GPT/Grok subscriptions preferred, so that production follows the agreed access policy.
44. As an editor, I want unavailable capabilities or exhausted quota reported, so that subscription failure never silently becomes paid usage.
45. As an editor, I want OpenRouter available with explicit launch confirmation, so that paid access remains a controlled usable route.
46. As an editor, I want each paid launch to show its concrete inputs, output count and available estimate, so that I understand what I authorize.
47. As an editor, I want an unknown price distinguished from an estimate, so that missing pricing is not presented as free generation.
48. As an editor, I want changed launches and paid corrections confirmed separately, so that an earlier confirmation is not a blanket budget grant.
49. As an editor, I want at most one automatic corrective generation for an observed obvious defect per requested operation, so that correction cannot become an uncontrolled loop.
50. As an editor, I want correction history and earlier results retained, so that another attempt does not hide what happened or replace my approval.
51. As an editor, I want repeated clicks to resolve to the intended saved job, so that accidents do not duplicate work or charges.
52. As an editor, I want in-flight jobs to retain frozen inputs while I draft another prompt, so that later typing cannot change authorized work.
53. As an editor, I want known work and interrupted downloads recovered without another generation, so that a local failure does not charge me again.
54. As an editor, I want uncertain submission outcomes visible, so that potentially billable requests are not reissued blindly.
55. As an editor, I want affected approvals invalidated when inputs or timing change, so that stale work cannot silently enter delivery.
56. As an editor, I want unrelated completed beats preserved during a revision, so that changes do not force unnecessary regeneration.
57. As an editor, I want real dimensions, frame rate and duration shown, so that profile shortfalls and upscaling are not disguised as native Full HD.
58. As an editor, I want approved AI coverage in the shared Resolve handoff with its beat, timing and provenance, so that it fits the editing workflow.
59. As an editor, I want supported portable review without the local server, so that saved review remains useful while live actions are clearly disabled.
60. As a maintainer, I want new providers to reuse the beat, job, approval and delivery contracts, so that extending access does not create another workflow.
61. As a maintainer, I want source, graphics, narration and read-only status behavior preserved, so that AI production does not regress the rest of the product.
62. As an editor, I want readiness claims backed by the corresponding real checks, so that passing mocks are not confused with usable account access or Resolve acceptance.

## Implementation Decisions

### Shared planning and domain boundaries

- Reuse the managing agent's original-scenario analysis, narrative beats and context. The AI module consumes routed beats; it does not introduce an independent full-scenario planner.
- Use the glossary distinctions between narrative beats, search fragments, AI scene alternatives, AI-generated assets, AI still approvals and AI sequences.
- Preserve the accepted catalog-search ADR: one level of search fragments, fragment-specific chains and existing three-option rules. Three AI alternatives do not change catalog behavior or mean three consecutive shots.
- Keep generated assets distinct from catalog candidates and authored graphics. Reuse the private project, Storyboard, review conventions, narration alignment, shared profile and delivery infrastructure.
- Preserve original narration and existing literal-source priorities. Do not invent speech or claims or require a new full-script fact audit before AI production.

### Scene choice and review surface

- Each AI beat retains its original scenario anchor, purpose/context, three distinct alternatives, comparison mode, selection and optional comment.
- Economy is the initial mode: descriptions first, then one selected image after explicit launch. Image comparison explicitly prepares three images and retains unselected outputs.
- Both modes retain the same quality expectations, visual style and authorization policy. Economy does not imply a cheaper model or different provider.
- Keep alternatives, selected result, prompt/files and next action in the shared Storyboard, with diagnostics/provenance in Details. Stages distinguish concept selection, still production/review, video production/review and readiness.
- Viewing/selection does not approve or generate. Follow-up actions start work directly without another chat command. Status/results update in place, preserving the selected beat and unsent prompts/files.
- Retain supported portable review/export behavior and clearly disable live-only actions when the authenticated local server is absent.

### Media, narration and approval

- Bind approval to an exact retained media version, its bytes and relevant production context. Text selection, generation success, still approval and sequence approval remain separate decisions.
- Animate the exact approved still. Retain and identify any content-preserving format derivative; semantic image changes require another still approval.
- Before recorded narration, allow still preparation/review only. Video requires an intact saved recording and resolved intended interval, reusing existing analysis/alignment instead of estimated duration.
- Cover that interval with one or more ordered clips, retaining placement, actual duration and source-still identities. Additional input stills require approval and additional generations remain bounded by the planned launch and authorization.
- Preview with corresponding narration and scene sound; deliver without embedding project narration. Suitable atmosphere/effects are allowed. Speech/music require an explicit request and actual output remains subject to human sound review.
- Preserve original provider media before local conforming. Verify decoding, dimensions, duration and frame rate. Prefer the shared profile where supported; show unmet required profiles instead of declaring readiness or disguising upscaling as native resolution.
- Relevant changes to an image, instruction, reference, narration interval, ordering or sound invalidate affected descendant review/readiness. Preserve unrelated completed beats. Historical approval is not approval of changed context.

### Prompt and reference context

- Accept ordinary prompts for corrections, refinement or different scenes; choose routine technical edit/regeneration mechanics without an editor-facing technical selector.
- Support optional image and video references in v1. Preserve original bytes, hashes, editorial instructions, beat/result association and analyzed derivatives/intervals.
- Inspect actual media and the requested interval. Reference analysis is distinct from provider support for raw video; it does not promise universal video-to-video generation.
- Clarify material ambiguity rather than silently choosing an interval. A filename, upload record or analysis claim alone is not inspection.
- Keep active references and unrelated instructions until replaced/canceled. Apply later instructions within their scope; a beat-local reference does not silently change the shared style.
- Freeze the revision target and context, retain historical context and never retarget a saved request to a newer background result.

### Providers and authorization

- Initial routes are suitable GPT/Grok subscriptions and confirmed OpenRouter API operations. Put transport-specific behavior behind a boundary shared by the production model so later providers reuse it.
- Describe actual operations, authentication/billing route, accepted references and output limits per adapter. Do not present an operation as available merely because another provider supports it.
- Prefer suitable subscriptions. Missing login, quota, model or capability produces an explicit waiting/unsupported state, with no silent provider/billing substitution.
- Validate native ChatGPT/Codex image access independently from text OAuth and API image-model availability. Do not advertise GPT subscription video without establishing a supported native route.
- Prevent Grok subscription access from falling back to static API keys. Published tools and an installed executable do not prove installed-account media capability.
- Confirm each OpenRouter launch against its frozen inputs, route/model and output scope. Show available pricing and distinguish unknown estimates. A three-image launch explicitly states that output count.
- Later jobs, changed inputs and paid corrections require separate matching confirmation. No blanket project budget grant is introduced.
- For an observed obvious defect, allow at most one correction per original editor-requested operation within authorized limits. No correction chains, reset allowance after restart or silent replacement of approved animation input. Paid correction waits for its own confirmation.

### Durable work and interaction contracts

- Save a stable job with frozen beat/alternative, prompt, reference/input hashes, route/model, requested output and applicable confirmation before provider submission.
- Distinguish submit intent, provider processing, retrieval and reviewable completion. A process exit, text answer or remote handle is insufficient: require intended locally saved, decodable media.
- Resolve repeated browser submissions to the intended existing job or an explicitly new operation. A reused request identity cannot silently carry different inputs. Drafts do not mutate in-flight requests.
- Persist provider handles and attempt/correction counts. Resume known work or download the same result without another generation. Unknown submission outcomes require reconciliation and cannot auto-resubmit.
- A bounded local worker executes the frozen request without an active desktop chat; it is not a separate scene-authoring agent hierarchy.
- Serialize state mutations through existing project locks and the recoverable journal. Preserve history/originals and unfinished work across interruption, without a parallel state store bypassing recovery.
- Status/result refresh is read-only and starts no recovery/generation. Preserve status's no-write, no-tree-creation and no-exclusive-lock contract.
- Extend the existing authenticated loopback server boundary. Confine uploads/media, validate actual files/identities and reject stale targets. Ordinary served state/logs must not expose secrets, OAuth tokens, private narration, signed URLs, arbitrary paths or commands. Intended narration preview remains bounded to its review context.
- Exact command/endpoint names, payload layouts and worker transport are implementation details to validate when implementation is assigned. Do not invent existing commands or freeze the design around a provisional scaffold.

### Delivery and documentation

- Reuse shared review and Resolve handoff. Deliver only intact, applicable human-approved AI coverage with its beat, source/output identity, ordering and timing; keep narration separate.
- Separate technical validity, editorial approval, material-use conditions and delivery readiness. Generated media is not documentary evidence or proof of unrestricted rights in references.
- Preserve originals, previous versions and user-edited delivery artifacts through existing protections. Repeat delivery must not replace foreign/modified files silently.
- Update operational guidance with the implemented workflow and verified capabilities, preserving compatibility and normal release/change documentation.

## Testing Decisions

### Accepted primary acceptance boundary

Use **editor-visible actions through the existing Storyboard/local-server workflow → durable project state and actual reviewable media → shared delivery** as the main feature-testing boundary. Test public actions and observable results, not new private helpers or exact internal JSON layouts.

Automated acceptance uses synthetic image/video/audio and mocked provider transports. Exercise the real local server, persisted state/recovery, media checks and browser interactions. This is one main product acceptance contour; focused adapter-contract tests check transport/authentication safety without introducing another business workflow.

Actual account/provider access and human/Resolve use are separate bounded acceptance steps. Mocks cannot satisfy them. Concrete generation scope and any spending need explicit authorization.

### Behavior coverage

1. Preserve original scenario routing and source/graphics behavior. AI may be proposed directly and each AI beat receives three distinct alternatives.
2. Economy defaults to descriptions, browsing/selection/comments make no generation call, and explicit launch creates the selected image only. Image comparison creates three outputs after explicit launch and retains unselected results.
3. Selecting text cannot approve an unseen image. Animation without exact approval is refused; changed bytes, substituted stills and stale/mismatched approvals are rejected.
4. Stills work before narration. Missing/changed recording or unresolved alignment blocks video. Several clips cover a longer interval with observable ordering/placement.
5. Prompt-only and image/video-reference revisions target the displayed version, inspect actual referenced content/intervals and preserve context/history.
6. Browser checks exercise generation, Apply, animation, progress/results/errors and retained-version comparison. Switch beats and type/select files while work runs; updates preserve drafts and never retarget a revision.
7. Paid work waits for matching confirmation. Changed launches cannot reuse it; three-image scope is explicit; unknown estimates remain unknown. Subscription failure cannot trigger OpenRouter automatically.
8. Duplicate clicks/restart resolve to one intended job. Later drafts cannot alter its inputs. Provider processing or a missing/invalid artifact cannot masquerade as completion.
9. Unknown submission cannot issue another generation. Known-handle recovery and interrupted downloads retrieve the same result, without a new charge or consuming a correction allowance.
10. At most one corrective generation is allowed across restart. Refuse chains, require paid correction confirmation and preserve approved input identity.
11. Relevant media/scenario/style/reference/timing/order/sound changes invalidate affected descendants only, preserving history and unrelated beats.
12. Real decoding/metadata checks distinguish valid media from empty/corrupt/truncated outputs and expose duration/profile shortfalls. VO remains separate; editorial content and sound require human review.
13. Server checks cover session/origin validation, stale targets, malformed requests, confined uploads and reference/media serving. No credential, signed-URL, private-narration or arbitrary filesystem leakage through ordinary endpoints.
14. Portable review retains its supported behavior, clearly disables live-only actions and triggers no generation on opening.
15. Delivery contains only applicable intact approved output, retains timing/provenance and rejects unsafe/changed destination media. Repeat delivery preserves foreign/user-edited files and reports conflicts.
16. Existing source, graphics, narration, CLI compatibility, read-only status and recoverable transaction behaviors keep their regression coverage.

### Existing test patterns to reuse

- Storyboard/local-server tests: generated review pages, session tokens, origin restrictions, allowlisted media and explicit saved decisions.
- Graphics review/reference tests: exact-version decisions, stale request targets, retained versions and private attachments.
- Narration tests: synthetic recordings and loopback provider fixtures for submit intent, unknown outcomes, resume, retrieval and read-only reporting.
- Narration-alignment tests: recording identity, ambiguous passages, resolved intervals and timing drift.
- Delivery tests: approved-media packaging, integrity, destination conflicts, foreign links and recoverable updates.
- Prefer these public workflow patterns and meaningful cross-module regressions. Avoid implementation-mirroring tests or tests requiring removal of an existing capability.

### Live and human acceptance

- Establish actual GPT subscription still generation and a prompt/reference edit with locally saved decodable artifacts and verified access route.
- Establish Grok subscription animation from the exact approved still, recording real dimensions, duration, audio and auth/billing route without secrets.
- Establish each claimed initial OpenRouter image/video operation under a concrete confirmed paid scope, including retrieval of the same result after download interruption.
- Inspect an economy beat, a three-image comparison beat, a reference-led revision using actual image/video content and an interval requiring several clips.
- Have an editor review retained results and use approved files in Resolve: placement, online media, decoding, sound, separate narration and profile shortfalls.
- Report source/documentation inspection, automated tests, browser verification, live media and human/Resolve acceptance separately. Missing evidence remains an incomplete acceptance gate.

## Out of Scope

- Implementation, scheduling/dispatching implementation, workers or live generation as a consequence of this specification task/publication.
- Blanket paid authorization, silent subscription-to-API fallback or re-submission of uncertain generation.
- Estimated-duration AI video before recorded narration, direct text-to-video bypassing exact-still approval or concept approval covering future images.
- Another scenario planner, recursive source-search subdivision or changes to catalog chains/query limits/three-option rules.
- A separate generic video-making application, wholesale donor WebUI/pipeline adoption, unneeded queue/service infrastructure or installing donor skills/code.
- Universal raw video-reference input, an independent video-to-video production mode or unsupported provider/model promises.
- Guaranteed GPT subscription image counts, parity with the newest API image model or GPT subscription video without a supported route.
- Unbounded automatic correction, silent input replacement, automatic human approval or generated media treated as source evidence.
- Unrequested music/speech or VO baked into generated clip audio; automatic final-film editing/publishing beyond the reviewed handoff.
- New providers beyond GPT/Grok subscriptions and OpenRouter in v1; the shared boundary must allow later additions.

## Further Notes

- The design interview settled the product choices, including the later three-alternative/two-mode revision. Earlier one-draft assumptions and conflicting donor demonstration controls are superseded.
- Donor research informs capability-sensitive controls, compact review, frozen requests, retained background work, explicit reference roles and selective rebuilding. It does not authorize copying a complete donor stack or require a technical edit/regenerate selector.
- Provider research dated 2026-10-16 establishes documented/source-level routes, not actual account entitlement or working media. Verify selected installed routes and current official schemas during authorized implementation. Missing required capability is an acceptance gap to resolve/report, not silently omitted scope.
- A bounded native provider turn is a possible worker mechanism. Generic text OAuth is not evidence of native image support. Establish access/billing identity separately for every claimed media route.
- Existing partial scaffolding is provisional and does not constrain this contract or establish completion. Its local tests do not replace the acceptance workflow.
- The configured project tracker carries this accepted specification with `ready-for-agent`. The label marks specification completeness; it does not instruct an agent to start. Implementation remains stopped until separately and explicitly assigned.
