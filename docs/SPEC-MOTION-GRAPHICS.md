---
type: specification
status: accepted
created: 2026-10-10
updated: 2026-10-10
issue: https://github.com/kovr33k/get-brolls/issues/52
tags: [get-brolls, motion-graphics, remotion, narration, integration]
---

# Integrate Remotion graphics with narration alignment and Storyboard review

## Problem Statement

A documentary creator needs authored graphics for scenario passages that footage alone does not explain well: numbers, timelines, geography, processes and relationships. The existing get-brolls workflow discovers and reviews material, but it does not provide an integrated way to author these graphics, locate them in a complete narration recording, render them locally, revise them in Storyboard and deliver editable, approved clips for montage.

Putting research, beat planning and every scene's implementation into one agent context overloads the planning task. Producing isolated animations without shared timing, evidence and version records also makes revisions and continuation unreliable. A saved video is insufficient if its displayed facts, source assets, narration interval or human approval cannot be traced.

## Solution

Add a complete first-stage Remotion workflow to the existing project and review experience. The managing agent selects graphics moments directly from the scenario and assigns each scene to a dedicated graphics specialist. That specialist researches displayed facts, designs the explanation, authors a template-based or custom composition, selects sound effects and prepares revisions. Work through scene assignments sequentially, saving each draft before continuing; review actual previews instead of requiring a separate plan-approval step.

Accept a complete narration recording and scenario, use Inworld STT for word timestamps, and match scenario passages to narration intervals. Estimated drafts and explicit timing remain supported. Render locally on Windows, retain every saved scene version and review graphics alongside found footage in the existing Storyboard. Saved revision requests are processed when the editor asks the managing agent in chat to apply them.

Deliver approved Full HD MP4 clips with sound effects, without embedded narration, plus timing information and editable sources for manual placement in Resolve. Establish this workflow with a five-concept pilot before adding model-based image/video generation. Collect the visual reference at the start of implementation work, before the first scene's visual authoring; technical specification preparation does not require it.

## User Stories

1. As a creator, I want Remotion graphics delivered as the first production stage, so that the workflow can mature before model-based media generation is added.
2. As a managing agent, I want to select graphics moments according to the scenario's meaning, so that animations explain the narrative instead of filling arbitrary time slots.
3. As a creator, I want the agent to save its scene plan and proceed directly to draft previews, so that I can evaluate concrete visuals without another plan-approval round.
4. As a managing agent, I want one graphics assignment per scene, so that the specialist has a bounded production task.
5. As a creator, I want several graphics scenes allowed in one chapter, so that assignment size does not impose a scene-count limit.
6. As a graphics specialist, I want the exact narration, surrounding chapter context and shared style in my assignment, so that the scene preserves the intended explanation.
7. As a managing agent, I want additional scene ideas returned as proposals, so that the specialist does not silently expand its assignment.
8. As a creator, I want a separate agent context for each scene, so that its research and revisions remain focused.
9. As a creator, I want scenes produced sequentially without waiting for feedback on every draft, so that the batch can progress while I review saved results.
10. As a creator, I want a scene waiting for an editorial answer to leave other assignments runnable, so that one uncertainty does not stop the whole project.
11. As a graphics specialist, I want templates for recurring numeric, timeline and map explanations, so that familiar tasks reuse a useful design.
12. As a graphics specialist, I want custom scene authoring when a template does not fit, so that processes and relationships are not forced into an unsuitable layout.
13. As a creator, I want custom sources retained and generalized only when a concrete repeat task appears, so that template growth follows actual use.
14. As a creator, I want both standalone graphics and graphics over real footage or photographs, so that the visual treatment fits each passage.
15. As a graphics specialist, I want to reuse suitable project media before finding missing material, so that scene production builds on the existing collection.
16. As a creator, I want acquired media to retain its origin, actual dimensions and reuse conditions, so that a rendered composition does not conceal source limitations.
17. As a creator, I want evidence for the numbers, dates and geography displayed in graphics, so that the animation does not turn unsupported scenario assertions into facts.
18. As a graphics specialist, I want saved values, units, definitions, reference dates and original sources, so that a chart remains understandable and editable.
19. As a creator, I want contradictory evidence reported with a proposed correction, so that I can decide how to resolve it without an automatic narration rewrite.
20. As a creator, I want only the affected scene paused by a factual conflict, so that unrelated scenes can continue.
21. As a creator, I want draft timing estimated from the scenario when VO is unavailable, so that early visual exploration remains possible.
22. As a creator, I want estimated timing clearly distinguished from narration-based timing, so that a draft is not mistaken for a montage-ready clip.
23. As a creator, I want to provide a complete narration recording and scenario, so that the system finds scene intervals without requiring manually cut audio fragments.
24. As a creator, I want Inworld STT used for narration analysis in the first stage, so that the agreed provider supplies recognized text and word timestamps.
25. As a creator, I want uncertain, repeated or missing narration matches exposed for correction, so that automatic alignment cannot silently choose the wrong passage.
26. As a creator, I want supplied audio fragments and explicit timecodes accepted, so that I can supply or correct timing directly.
27. As a creator, I want completed transcription reused when the recording and provider settings are unchanged, so that continuation and visual revisions do not repeat paid analysis.
28. As a creator, I want known Inworld operations resumed and unknown submission outcomes reported, so that recovery does not blindly resubmit an uncertain paid request.
29. As a creator, I want narration-derived intervals converted consistently to the project's frames, so that animation duration and placement agree with the editing profile.
30. As a creator, I want the visual reference collected when work begins, so that specification preparation can finish without prematurely choosing a style.
31. As a creator, I want one shared composition profile, so that all scene outputs use Full HD and the intended project frame rate.
32. As a creator, I want 30 fps for a new project and the confirmed fps for an existing project, so that the output follows the agreed editing context.
33. As a creator, I want rendering performed locally on Windows, so that the first stage works without setting up a cloud-rendering deployment.
34. As a maintainer, I want Remotion dependencies optional for ordinary collection commands, so that graphics support does not burden users who only search for material.
35. As a creator, I want up to two scene-code repair attempts after a technical rendering failure, so that bounded automatic recovery can fix a scene without looping indefinitely.
36. As a creator, I want errors and partial authoring preserved after the repair limit, so that the failure is inspectable while other assignments continue.
37. As a creator, I want suitable existing sound effects selected and synchronized by the scene specialist, so that effects support the animation without a separate sound-planning agent.
38. As a creator, I want permitted basic effects from the CC0 subset of @remotion/sfx saved locally, so that the sound collection supports repeatable rendering.
39. As a creator, I want each effect's source, terms, placement, trim and level retained, so that sound revisions remain traceable.
40. As a creator, I want to hear the relevant VO interval with graphics and effects during review, so that I can judge timing and speech intelligibility.
41. As a creator, I want graphics and found footage in the same Storyboard, so that I can review their role in the scenario together.
42. As a creator, I want every saved version's preview, code, data and evidence retained, so that I can compare variants or return to an earlier result.
43. As a creator, I want revision requests tied to the scene and version I reviewed, so that a comment is not silently applied to a different result.
44. As a creator, I want Storyboard comments saved and processed after my chat instruction, so that the first stage does not require an autonomous agent-launching UI.
45. As a creator, I want a scene comment to affect only that scene by default, so that a local revision does not unexpectedly change the whole film.
46. As a creator, I want explicitly scoped shared changes supported, so that I can intentionally update several scenes when required.
47. As a creator, I want approval tied to an exact saved graphics version, so that changed visuals or sound require renewed review.
48. As a creator, I want unchanged scenes to retain their decisions when another scene changes, so that revision work does not repeat unrelated approvals.
49. As a creator, I want continuation to resume from verified saved work, so that an interrupted agent session does not restart the project or lose questions and repair counts.
50. As a creator, I want narration, data, style or asset changes to invalidate only their dependent results, so that reuse remains safe without discarding unrelated completed work.
51. As a creator, I want status and review viewing to report saved state without initiating analysis or rendering, so that checking progress has no production side effects.
52. As a creator, I want ready MP4 clips containing their selected sound effects and background, so that I can place the finished compositions directly in Resolve.
53. As a creator, I want VO kept out of delivered graphics clips, so that the complete narration remains a single separate editing track.
54. As a creator, I want timing information and editable sources alongside delivered clips, so that placement and later changes remain possible.
55. As a creator, I want transparent layers produced only after an explicit request, so that routine delivery contains the agreed finished clips.
56. As a maintainer, I want existing collection projects, reviews, locks and recoverable writes preserved, so that adding graphics does not break the established workflow.
57. As a maintainer, I want offline behavioral tests using synthetic media and provider fixtures, so that routine verification does not require real credentials or paid calls.
58. As a creator, I want acceptance to include real Windows rendering, actual Resolve use and human review, so that green automated tests alone do not establish editorial readiness.
59. As a creator, I want HyperFrames considered only after an explicit need assessment, so that a second renderer adds demonstrated value.
60. As a creator, I want future generated assets explicitly identified in the same project workflow, so that later extensions preserve provenance and version-specific review.

## Implementation Decisions

### Scope and agent responsibilities

- Remotion is the sole integrated renderer in this stage. Use hybrid template and custom authoring, including standalone scenes and completed overlays. The initial pilot exercises numeric graphics, a timeline, a map, an explanatory schematic and a relationship diagram.
- The managing agent owns original-scenario planning and assignment selection. Extend the operational skill instructions to describe delegation, sequential production, recovery, revision processing and honest reporting of incomplete work. Preserve the catalog search contract and generate the installed skill mirror through the established workflow.
- The graphics specialist owns research of displayed facts, visual design, source authoring, sound selection, preview preparation and revisions. Assign one scene per specialist context, with shared style and chapter context. A recurring visual concept appearing at noncontiguous narration intervals receives separate timed occurrences; never join distant passages merely to enforce a five-clip count.
- Save a plan and produce drafts directly, without adding a separate plan-approval gate. Human feedback follows previews; final approval remains a human decision. New scene proposals return to the managing agent for separate assignment.
- Execute scene assignments sequentially. Save results before the next scene, and continue other assignments when one waits for an editorial answer. Resume the original scene context when available; otherwise reconstruct its assignment from persisted evidence and sources.

### Executable module interfaces

Reuse the existing project CLI as the principal executable interface. Its structured JSON success/error reports, explicit project selection and serialized write operations remain authoritative. Expose the following capabilities without creating a second orchestration application:

| Module | Required caller-visible capability |
|---|---|
| Narration alignment | Submit or resume recording analysis, reuse a transcript, locate scenario passages, report uncertainty and save explicit timing corrections |
| Graphics scenes | Record assignments and evidence, report blocking questions and stages, save/finalize versions and retain dependency fingerprints and repair counts |
| Remotion rendering | Validate one saved composition, render one version with its profile and return checked artifacts or technical diagnostics |
| Storyboard review | Present graphics in scenario context, play relevant narration and effects, compare versions and exchange saved human decisions and revision requests |
| Clip delivery | Deliver the approved, current and permitted result with timing information and editable sources, recording its exact version identity |

These are responsibilities, not a requirement for five separate services or pass-through wrappers. The agent host performs LLM planning and delegation. The Python CLI manages project work and invokes an optional Node rendering module; it does not become a resident LLM executor. The social-source queue retains its existing role.

### Persisted contracts and compatibility

- Extend the shared project manifest, recoverable transaction journal and saved snapshots with explicit, independently validated graphics, narration and style records. Keep discovered candidates as candidates; do not fabricate source providers to store graphics. Legacy records without the new sections remain valid and usable, and existing review exchanges retain their compatibility contract.
- A graphics assignment retains stable scene/occurrence identity; original scenario anchors and narration; chapter context; visual purpose; shared style revision; project composition profile; selected timing basis; known facts and material references; and unresolved questions. These inputs are sufficient to restore work without relying solely on agent chat history.
- A graphics version retains stable scene and version identities, parent-version relation, authored composition and properties, template/authoring revision, factual values and evidence, referenced local asset identities and hashes, precise narration times and derived frame intervals, sound cues and levels, runtime/render configuration, result artifacts and diagnostics. Save every completed version; never overwrite a previous version to implement a revision.
- Maintain work-in-progress stages for assignment, research, authoring and rendering, with explicit waiting and error outcomes. Readiness for review requires verified declared artifacts. A temporary file or partial video does not establish a saved complete result. Approval and delivery are separately recorded decisions/outcomes, not implications of render success.
- A revision request retains project, scene, reviewed-version identity, requested text and scope, stable request identity and processing outcome. Re-import or continuation does not silently process the same request twice. An older-version request retains its actual context; it is not automatically retargeted.
- Approval records the human decision and exact version/content context. New or changed versions require renewed approval. Preserve earlier decisions for history and possible return, while changes to relevant inputs or reuse conditions may make a prior result ineligible for the current scenario use.
- Store project authoring sources, data, evidence, narration results and reusable local assets outside the product source tree. Keep rendered previews, clips and saved reviews in the corresponding existing project artifact routes. Validate identifiers and project-relative references before accepting them; invalid state is reported without resetting history.

### Displayed facts and source materials

- Research the facts displayed in a scene, rather than requiring a complete script fact check. Preserve original sources, indicator definitions, units, geography, reference dates and applicable terms. Retain editable numeric data instead of treating a chart screenshot as a dataset.
- If research conflicts with narration, save the discrepancy, source and proposed correction; block only that scene pending the editor's decision. Do not rewrite the scenario or render an apparently settled correction without that decision.
- Reuse suitable project materials first, then acquire missing video or images through the existing get-brolls routes and constraints. Existing search limits, visual suitability assessment, human approval and reuse conditions still apply to source candidates. Preview access does not establish permission for final delivery.
- Data portals and sound collections are research starting points, not mandatory provider chains or requirements to implement a connector for every site. Save the actual selected data, media, fonts and sound bytes with provenance, terms and hashes before repeatable rendering.

### Narration analysis and timing

- Use Inworld STT as the first-stage provider for the complete recording, requesting word timestamps and retaining transcript, timing and operation results locally. Use the documented asynchronous route for long recordings. Current provider documentation supports word timestamps; recognition confidence is not populated and must not be used as the alignment confidence score. [Async transcription](https://docs.inworld.ai/stt/async-transcription), [STT reference](https://docs.inworld.ai/api-reference/sttAPI/speechtotext/transcribe.md).
- Preserve original recognized and scenario text while normalizing a copy for matching. Match passages in narrative order using text anchors, surrounding context and sequence similarity. Missing, repeated, reordered or competing passages yield explicit match evidence and uncertainty; STT alone is not forced alignment to the supplied scenario.
- Retain precise times in the narration clock and derived scene-frame intervals in the shared profile. Validate finite ordered bounds against the recording or supplied fragment. Specify one deterministic frame-rounding convention for all callers, with conversion error bounded by a frame at each boundary; save that convention and the original times. Explicit corrections remain tied to the relevant recording and scenario revision.
- Estimated script timing permits draft previews but is labelled visibly. Final VO-timed delivery uses resolved narration matching or supplied explicit timing. Uncertain automatic matches cannot silently become established intervals. An unresolved timing question blocks the affected final delivery while allowing other scenes to progress.
- Maintain separate fingerprints for provider analysis and scenario matching. Unchanged recording and provider settings reuse completed STT; changed scenario anchors or timing corrections can require rematching without retranscribing unchanged audio. Changes to actual provider configuration invalidate the relevant analysis result.
- Persist submission intent and input fingerprint before a paid request, retain its operation identity when returned, and collect a durable transcript after completion. Resume known operations without another submission. Unknown submission outcomes and expired/unavailable results are reported explicitly; no blind retry or exactly-once billing promise is made.
- Credentials remain in private environment/configuration. Validate input and provider configuration before submitting; keep keys and signed result URLs out of logs, review exports and public artifacts. This specification authorizes implementation of the integration, not paid calls during specification preparation.

### Local rendering, templates and effects

- Add optional Remotion authoring/render dependencies alongside the Python core, preserving ordinary collection without them. Pin compatible runtime dependencies and identical exact Remotion package versions, provide an explicit setup/diagnostic route, and record the tested runtime and renderer configuration. Missing graphics dependencies produce an actionable graphics error instead of breaking source search. The official [Node renderer](https://www.remotion.dev/docs/ssr-node) provides the local rendering route; [Remotion's package guidance](https://www.remotion.dev/docs/sfx) requires matching package versions.
- The renderer takes a saved composition/version and declared profile, renders to a staging result and verifies it before publication. Use Full HD 1920 by 1080. Default to 30 fps for a new project; use the confirmed editing fps for an existing one. Run one scene render at a time with explicit bounded worker settings suitable for the machine.
- Use MP4 with H.264 video and AAC effects audio as the initial ready-clip profile. Record explicit quality settings and verify decoding, dimensions, fps, frame count/duration and expected audio. Final effects-only clips must not contain VO; review playback supplies the relevant VO interval. Validate quality in the actual Resolve project rather than inferring it from the codec name.
- Grow a small template library from numeric, timeline and map tasks. Keep explanatory and relationship scenes custom when needed. Sources are preserved regardless of template status; generalization requires a concrete reuse case. Template reuse does not validate a new scenario's facts or timing.
- The specialist selects existing effects and synchronizes them to visual events. Reuse local sounds first; the preferred missing-basic-effect route is the suitable CC0 subset of @remotion/sfx. The package exports remote URLs, with MIT code and individual sound terms, so materialize selected permitted files locally rather than assuming every exported sound has the package-code license. [Collection](https://www.remotion.dev/docs/sfx), [CC0 whoosh example](https://www.remotion.dev/docs/sfx/whoosh).
- Sound cues retain asset identity, placement in scene frames, trim/duration and gain. Evaluate the mix with narration for intelligibility and clipping. Other permitted imports may cover missing sounds, without requiring automated crawling or a universal sound-search connector. Respect the difference between finished-video use and permission to redistribute raw source assets.
- Allow at most two scene-code repair-and-render attempts after a technical authoring failure, preserving the intended meaning and consumed attempt count. Exhaustion retains diagnostics and partial work and leaves the scene unresolved while other assignments continue. This allowance does not apply to factual changes or repeated STT submission.

### Review, revision and continuation

- Extend the existing Storyboard and saved-review exchange to show graphics and footage together, with narration anchors, timing basis, previews, saved versions, evidence and unresolved questions. Graphics review includes the corresponding VO interval with effects. Estimated drafts remain visibly estimated. A separate Remotion Studio review requirement is not introduced.
- Save revision requests in Storyboard; processing begins when the editor instructs the managing agent in chat. Saving or viewing a request does not launch an agent. A scene-local request changes that scene only; an explicit shared-scope request may create new versions of several affected scenes.
- Validate project identity, exact version/content context and decision freshness on review import. Reject or report stale entries without losing valid entries or fabricating human approval. Preserve the existing local review server's token, allowlist and path-validation behavior for newly exposed preview assets.
- Continue from verified durable stage results after interruption. Reuse depends on intact artifacts and relevant input fingerprints, including narration/timing, scenario context, style, data, assets, authored code, template and runtime/render profile. A shared change invalidates its dependents rather than every project item.
- Keep write operations under the existing project serialization and recovery contract. Status remains read-only: no project-directory creation, exclusive writer lock, journal recovery, rendering or paid analysis. Opening or browsing review results does not trigger those production actions. Saving/importing an explicit human decision is still a write operation.

### Delivery and rollout

- Deliver only an approved version whose declared artifacts are intact, final timing is resolved and required source-use conditions and factual questions are settled. Identify scene, occurrence and approved version in clip metadata and the timing list. Preserve original narration times and frame intervals for manual montage placement.
- Deliver the completed visual composition with selected effects and background. Keep complete VO as a separate editing track. Include editable authored sources, data/evidence and referenced assets to the extent their terms permit; do not redistribute restricted raw material merely because it is present in a rendered clip. If editable source material needs separately held assets, identify that dependency explicitly rather than silently presenting an incomplete self-contained package.
- Do not automatically create a transparent layer, alternate master or a separate effects stem. A transparent export may be handled after an explicit request and is not a first-stage acceptance requirement. Preserve existing delivery collision and foreign-file protections.
- Implement incrementally within this first stage: establish shared scene/version state and a real local render/review/delivery cycle, integrate complete-recording narration alignment and bounded continuation, then complete template/custom pilot coverage. These are delivery milestones for the same scope, not authorization to stop at a rendering prototype.
- Collect the reference when work starts, before visual authoring of the first scene. It determines scene/template appearance and can require specific assets or visual dependencies. Its absence does not block this specification or generic infrastructure design; style-specific authoring and visual acceptance wait for that input.
- Later generated media will need explicit generated-asset identity and production provenance in the same project workflow. Preserve that distinction without adding empty provider factories or generation endpoints now. Possible FCPXML with VO is an independent later delivery extension.
- *Before any HyperFrames stage, assess how much it is needed and what demonstrated capability or workflow improvement it adds to the established Remotion workflow. Adoption, deferral and omission remain valid outcomes.*

## Testing Decisions

### Agreed test seam

The creator confirmed testing through the existing public project CLI and Storyboard workflow. This is the primary behavior seam: create a scene, render, save/review a version, request a revision, approve the intended result and deliver it. Tests exercise caller-visible JSON reports, saved artifacts, recovery and human review exchange; they do not prescribe internal helper calls or one unit test per implementation function.

Use the highest practical existing seam. Narrow provider/renderer fixtures are dependencies beneath the CLI seam, not a new production orchestration layer. Pure text-matching tests may supplement workflow coverage where they demonstrate a meaningful ambiguous or missing match; avoid tests that merely duplicate implementation steps.

### Automated verification

- Use synthetic video, images, narration and sound effects in isolated temporary projects, with controlled Inworld HTTP responses and rendering fixtures where a real render is unnecessary. Ordinary tests must not contact paid services, require personal credentials or use private scenario/media originals.
- Verify the CLI lifecycle for an estimated draft and a narration-timed version, immutable saved versions, exact-version approval, delivery metadata and rejection of unresolved/stale/incomplete results. Include a project containing both discovered footage and graphics, plus a legacy project with no new records.
- Verify STT submission/polling/completion and result reuse, absent recognition confidence, missing or zero-valued timestamp handling according to provider format, ambiguous/repeated/omitted passages and explicit timing corrections. Changing only scenario matching inputs must not resubmit unchanged provider analysis. Unknown submit outcomes, known pending operations and unavailable results must not turn into silent paid retries.
- Verify dependency invalidation independently: local scene revisions leave other scenes intact; shared style, changed assets or corrected timing affect only recorded dependents; old source bytes and decisions remain available for history. Detect missing or modified artifacts instead of treating their filenames as cache evidence.
- Fault-inject interruption before and after durable writes and during render publication. Verify deterministic continuation, preservation of waiting questions and consumed repair attempts, no duplicate version/request processing, and no completed-scene claim for a partial output. Exercise conflicting writers and malformed records through the CLI without resetting the project.
- Extend read-only status tests with graphics/transcription states and pending journals. Confirm no project-content writes, new directories, exclusive writer lock, render process or provider submission from status or review viewing.
- Exercise Storyboard in a browser: mixed media, version switching, narration/effect playback, saved scene comments, explicit shared scope, approval/export/import, stale entry handling and normal narrow-screen operation. Retain affected print/export behavior and security checks. Saving a comment must not start an agent.
- Exercise the public render/delivery path with a small real Remotion composition on Windows once dependencies are prepared. Verify declared output metadata and decoding; synthetic signals can prove effects inclusion and VO exclusion. Tests requiring renderer setup identify unmet prerequisites and do not masquerade as passed real renders. Preserve foreign outputs and delivery collision behavior.
- Check the optional dependency contract, documented CLI help/JSON envelope, operational guide updates and generated skill mirror. Ordinary collection remains usable without the graphics runtime. Run focused checks during development and the repository's required Windows CI checks before integration, reusing valid evidence only for the tested state.

### Prior art

The existing suite already has a shared CLI subprocess harness, synthetic FFmpeg media helpers, public-command delivery and lock tests, read-only status snapshots, recoverable manifest/journal cases, partial and stale Storyboard decision imports, local review-server allowlist tests and preservation of foreign delivery files. Extend those patterns and their caller-visible assertions rather than introducing a parallel test harness.

### Live and human acceptance

Acceptance is required on all five selected pilot concepts: numeric comparison, historical timeline, disputed-area map, process schematic and relationship diagram. Repeated appearances count as distinct timed occurrences where the scenario requires them; acceptance covers the chosen concepts rather than insisting on exactly five continuous clips.

1. Produce the required reference-based visual style and obtain human approval of the finished versions, with dated evidence for displayed facts and resolved conflicts.
2. Analyze the actual complete narration, locate required intervals and demonstrate correction of uncertain matches. Save the results and show unchanged completed analysis reuse on continuation.
3. Demonstrate Storyboard review with VO and effects, saved revision requests processed after chat instruction, comparison of retained versions and version-specific approval.
4. Render locally on Windows and demonstrate actual import, playback, timing placement and acceptable visual/audio quality in Resolve. Output is Full HD at the confirmed project fps, with effects embedded and VO separate.
5. Demonstrate interruption continuation without repeating unchanged finished work, losing source evidence/versions, resetting repair limits or falsely treating partial artifacts as finished results.

Keep live evidence and private pilot media outside the source tree. Record tested versions, configuration, observed outcomes and remaining limits without exposing credentials or scenario originals. Local automated tests, real renderer checks, live STT access, Resolve use and human editorial approval are distinct evidence; none automatically establishes the others. This specification does not claim any of these acceptance checks have already passed.

## Out of Scope

- Model-based image/video generation and integration with Seedance, Kling, fal, OpenRouter or equivalent generation providers.
- HyperFrames implementation before the explicit need assessment, and mandatory side-by-side integration of multiple renderers in this stage.
- Cloud/AWS rendering deployment, local speech recognition and replacement of the selected first-stage narration provider.
- A resident LLM orchestration server, autonomous agent launch from Storyboard, parallel scene production or repurposing the social-source queue as a universal paid-job executor.
- Full-script fact checking, automatic narration rewrites, unsourced quantitative claims, inferred human approval or permission to use found media.
- A second review application or timeline editor, automatic montage assembly, FCPXML with VO, mandatory alpha/master/stem exports, generated sound effects or background-music selection.
- Hard-coded data-provider chains, connectors for every statistics or sound website, indefinite search/render retries, and immediate generalization of every custom scene.

## Further Notes

The complete architecture and the public CLI/Storyboard testing approach are accepted. This specification synthesizes that scope; it does not authorize changes to the agreed stage order or silently expand it into model-generated media.

The visual reference is deliberately deferred until implementation starts. Freeze the shared visual requirements after inspecting it, and assess any concrete extra dependency or performance needs then. Exact compatible dependency versions, public command naming, schema encoding and conservative renderer limits are engineering preparation within the accepted module interfaces, not another product-policy interview. Document them before implementing their affected routes, and calibrate matching and output quality through the pilot.

Publication with the ready-for-agent label marks the specification ready for implementation planning; it does not claim product implementation, live-provider acceptance or release completion. Follow the repository's existing branch, review, CI and integration rules when implementation is requested. Keep private narration, reference media, scenario originals and account details outside public issues and fixtures.

## Initial visual direction — 2026-10-10

Initial visual authoring may begin with a proposed documentary style without a supplied external reference. Save that direction as an explicit proposed style revision and show its actual rendered preview for editorial feedback. This permits the first scene's authoring; it does not infer human approval or freeze the visual direction for all later scenes. An external reference may refine the style later, with affected versions reviewed again.
