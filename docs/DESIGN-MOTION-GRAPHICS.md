---
type: specification
status: accepted
created: 2026-10-10
updated: 2026-10-10
tags: [get-brolls, motion-graphics, design]
---

# Motion graphics: staged design

This document records the accepted scope and consolidated architecture for adding authored graphics and animation to get-brolls. The human editor confirmed the complete architecture on 2026-10-10. Visual direction and exact implementation contracts remain to be prepared; acceptance of this design is not evidence of implemented or validated renderer support.

## Settled scope

- Deliver incrementally. The first stage integrates and matures the complete motion-graphics workflow with Remotion as its sole integrated renderer.
- HyperFrames is a possible later stage, conditional on a separate assessment of its practical need.
- The first stage produces graphics and animated video through scene authoring and rendering. Authoring is hybrid: use graphics templates for familiar tasks and author a custom graphics scene when an existing template does not fit the visual purpose. Initial coverage includes numeric graphics, timelines, maps, explanatory schematics and relationship diagrams.
- Model-based image and video generation, including Seedance, Kling and equivalent providers, belongs to a later stage after the graphics workflow is mature.
- Future model-based image and video production is architectural context. It does not require generation endpoints, a general-purpose paid-generation job executor or image/video provider integrations in the first stage. Narration analysis is a separate first-stage requirement.
- Plan extension boundaries for later production capabilities while keeping the current implementation scope focused on graphics.

## Later renderer checkpoint

\* Before starting a HyperFrames stage, assess how much it is needed and what useful capabilities or workflow improvements it would add to the established Remotion workflow. Its integration is conditional: the assessment may lead to adoption, deferral or omission.

## Template evolution

Grow the graphics-template library from concrete recurring tasks. Start with a small set for the pilot's numbers, timelines and maps, alongside the custom explanatory and relationship scenes. A successful custom scene becomes a reusable template when there is a clear repeat use to support; do not require every approved scene to be generalized immediately.

Keep each scene's editable sources regardless of whether it becomes a template. Template reuse is a separate decision from saving scene versions and does not establish that another scenario's facts, media or timing are valid. The technical template interface and version records will be defined with the implementation design.

## Planning workflow

The managing agent selects graphics moments from the scenario, records the proposed plan and delegates draft scene production to the graphics specialist without a separate human approval of the plan. Human feedback is based on the actual previews and drives revisions; final approval of a finished scene remains a human decision.

Support both standalone graphics scenes and graphics overlays on real video or photographs. The managing agent chooses the composition according to the scenario fragment's visual purpose. Graphics and discovered material can therefore contribute to the same fragment; this does not revise source provenance, reuse conditions or human approval requirements. Overlay delivery follows the completed-clip policy in the editing handoff below.

## Factual inputs

The agent prepares and verifies the numeric, dated and geographic facts that will actually appear in graphics, rather than treating scenario assertions as verified data. Preserve source links and reference dates. Research is limited to the scene's displayed information; this decision does not require a complete fact check of the scenario.

When verified data contradict the scenario, report the discrepancy with its source and a proposed correction. Pause the affected scene until the human editor decides how to resolve it; other scenes may continue. Preserve the original scenario rather than silently changing its narration or rendering a corrected version as if the conflict were settled.

### Data-source references

These are researched starting points, not implemented connectors or a mandatory source order. Choose the original data appropriate to the indicator, region and time period; preserve its definitions, units, provenance and applicable reuse terms.

| Resource | Relevant access | Use in graphics research |
|---|---|---|
| [World Bank](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation) | Public Indicators API without API-key authentication | Country indicators and time series; inspect the indicator's metadata and [dataset terms](https://data.worldbank.org/summary-terms-of-use) |
| [Our World in Data](https://ourworldindata.org/easier-to-reuse-our-data) | CSV data and JSON metadata for charts | Discover comparative series and follow their original sources; third-party data keeps its [original licensing terms](https://ourworldindata.org/faqs) |
| [Gapminder](https://www.gapminder.org/data/) | CSV/XLSX indicators and bulk datasets | Long comparative series; keep original-source attribution and distinguish observed values from estimates where the methodology requires it |
| [Eurostat](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction) | Public data and metadata APIs | Statistical datasets, especially for European comparisons; save the actual fetched data because the database exposes the current dataset version |
| [Statista](https://www.statista.com/getting-started/working-with-statista-statistic-download-formats) | XLS statistics with source metadata; access depends on the account and material | Optional research route or supplied-file import; publication and automation need the relevant [access and usage terms](https://www.statista.com/getting-started/publishing-statista-content-terms-of-use-and-publication-rights) |

For animation from numerical data, retain the values and metadata rather than treating a screenshot of a finished chart as an editable dataset. Reusing an existing chart image is a separate material-use decision.

## Real media inputs

The graphics specialist may obtain the real video and photographs needed for its assigned scene. Reuse suitable material already recorded in the project first, then find missing material through the existing get-brolls workflow. Keep the source identity, provenance and reuse conditions in the shared project records.

Use the existing source capabilities, configured constraints and acquisition/preview routes. Material discovery does not itself establish suitability, human approval or permission to publish a finished composition. The renderer receives the selected working assets; source discovery remains part of the project workflow rather than rendering.

## Timing inputs

Draft scene production may begin from the script with an estimated duration. Final scene duration and animation timing use recorded narration or explicit timecodes. Preserve the timing basis so an estimated draft is distinguishable from an audio-timed version.

The first Remotion stage must accept a complete voice-over track together with the scenario and automatically locate the narration intervals needed by selected scenes. Show uncertain matches for human verification rather than treating them as established timing. Supplied audio fragments and explicit timecodes remain valid inputs or corrections.

Use Inworld Speech-to-Text as the primary narration-analysis provider in the first stage. Local speech recognition is deferred. Send the recorded narration for transcription with word timestamps, then match the recognized text to the supplied scenario to derive scene intervals. Inworld's transcript is an input to scene matching, not a ready-made scene plan or proof of correct alignment.

Retain the returned transcript and timing data in the project for scene production and revisions. Reuse a checked, completed analysis result when the recording and analysis settings have not changed, according to the recovery policy below. Detailed cache keys and technical input formats remain to be specified. This design choice does not establish an implemented or live-validated integration.

The current [asynchronous transcription guide](https://docs.inworld.ai/stt/async-transcription) documents long-recording input and word timestamps. The current [STT reference](https://docs.inworld.ai/api-reference/sttAPI/speechtotext/transcribe.md) states that recognition confidence is not populated: synchronous/streaming results return zero and asynchronous results omit it. Assess uncertain scene matches from the matching evidence rather than treating this field as a confidence score. Verify the integration and scene-boundary quality on the actual pilot narration.

## Graphics specialist

Separate the managing agent's editorial planning from a dedicated graphics specialist's work. The specialist owns the complete assigned-scene workflow: factual research, visual concept, Remotion authoring, draft previews and revisions. Each graphics assignment covers one scene; it does not limit the number of graphics scenes in a chapter.

When the managing agent selects three graphics scenes in a chapter, create three assignments. Each receives the relevant chapter context and shared style requirements. If the specialist proposes an additional scene during its work, return that proposal to the managing agent for inclusion in the plan and a separate assignment.

- The managing agent retains the scenario context and selects graphics moments and their visual purpose. Assignment inputs include stable scene/fragment identity, exact narration, surrounding context, known facts and media, and available timing and style requirements.
- The graphics specialist researches displayed facts and original data sources, develops the visual explanation, authors Remotion compositions, selects and synchronizes sound effects, prepares draft previews and applies scene revisions.
- The CLI performs rendering and records artifacts and state through the shared project workflow. Specialist results include source evidence, saved data, scene sources, preview references and explicit unresolved questions.

The handoff should preserve the original narrative and meaning. Return contradictory or missing evidence explicitly rather than silently rewriting narration to fit a chart. A research portal is a starting point; the original dataset, indicator definition, units, geography, time period and reuse terms determine whether a proposed comparison is appropriate.

## Scene execution

In the first stage, execute graphics assignments one at a time. The specialist prepares a scene's draft, saves its result and then moves to the next assignment without waiting for human feedback on every draft. A scene requiring clarification waits for its answer while the workflow continues with other assignments. Final human approval remains a separate requirement for each finished scene.

Give each scene its own graphics-agent session and context, carrying the assignment, relevant chapter context and shared style requirements. Revisions return to work on that same scene rather than accumulating all scenes of a chapter in one session. The session boundary and sequential execution are separate decisions: scene sessions are worked one at a time.

Render Remotion scenes locally on Windows in the first stage. Keep scene authoring sources and rendered results in the local project. Cloud rendering is deferred rather than requiring AWS deployment as part of the pilot. Local rendering and the external narration-analysis provider are independent parts of the workflow.

The current [rendering CLI](https://www.remotion.dev/docs/cli/render) and [renderer API](https://www.remotion.dev/docs/renderer/render-media) document local rendering; supported-platform details are in the [system requirements](https://www.remotion.dev/docs#system-requirements). This renderer is not yet integrated or validated in get-brolls. Exact dependency versions, resource limits and technical checkpoint schemas remain implementation specification work. Narration analysis uses the provider selected in the timing policy above and the ordered matching approach in the consolidated architecture below; matching thresholds need pilot calibration.

For a technical error in a scene's authoring code, allow the specialist up to two repair attempts followed by another render, preserving the scene's intended meaning. If neither attempt succeeds, retain the error and work completed so far, report the unresolved scene and continue other assignments. This allowance applies to scene-code repair, not repeated narration-analysis submissions or automatic factual changes.

### Recovery and result reuse

Persist each scene's saved results and current work stage. After an interruption, a continuation request checks those records and resumes unfinished work rather than restarting the entire project. A partial output is not treated as a completed scene. Preserve pending questions, recorded decisions and the existing repair-attempt limit when continuing.

Reuse completed scene results and the Inworld transcript when their relevant inputs and settings are unchanged. A continuation request alone is not a reason to resubmit the same completed narration analysis. Changes to narration, scene data or shared style invalidate the affected dependent work; produce new versions for renewed human review while preserving previous versions. Detailed dependency signatures and checkpoint records remain technical design work.

Use the existing serialized project-write and recovery contracts. Read-only status and opening the review interface do not themselves initiate rendering, paid analysis or recovery writes.

## Scene versions

Keep each saved version of a graphics scene, including its rendered video, authoring sources, used data and recorded source evidence. A revision produces a new version while preserving the previous one for direct comparison and return. Do not reduce the retained videos to only the latest and approved versions.

These versions belong to the same scene and do not count as additional scene assignments merely because their appearance or timing changed. Their storage organization follows the consolidated architecture below; exact approval and checkpoint schemas remain implementation specification work.

## Review interface

Extend the existing Storyboard as the shared review interface for discovered footage and authored graphics. Keep both visible in the scenario context. For a graphics scene, show its rendered preview, saved versions, source evidence and a way to request a revision tied to that scene. Human scene approval is made in this shared interface; Remotion Studio is not a separate required review destination.

When recorded narration is available, review the scene and its selected sound effects together with the corresponding voice-over interval so that timing and speech intelligibility can be assessed. This review playback does not require narration to be embedded in the delivered clip. A script-timed draft without recorded audio remains visibly marked as estimated timing.

This is an accepted interface direction, not implemented functionality. The demonstrated interface is a local mockup rather than a rendered Remotion scene or an actual project approval. The consolidated architecture below defines the initial delivery profile.

### Revision scope and approval

A revision request saved in Storyboard does not itself launch an agent. For the first stage, the editor saves scene comments and then asks the managing agent in the current chat to process revisions. That explicit continuation reads the saved requests and delegates them to the affected scene's specialist. A separate autonomous execution mechanism triggered by the review page is outside this stage.

Bind each saved request to its project, scene and reviewed version, retaining its text, scope and processing result. Processing a request twice must not silently create duplicate revisions. If a request targets an older version, show that context and retain the request rather than silently applying it to a different version. Use the existing saved-review exchange; the exact extension schema is implementation specification work.

A revision requested on a graphics scene applies to that scene by default. Do not infer a project-wide style change or automatically alter similar scenes. An explicit request such as applying the change to all graphics may cover several scenes; record that scope and create new versions of the affected scenes.

Human approval belongs to a specific saved graphics version. Changed versions require renewed human review and approval; approval of an earlier version does not transfer automatically. Unchanged scenes are not revised or sent back for approval merely because another scene changed. Preserve prior versions and their recorded decisions for comparison and return, subject to the existing provenance and reuse-condition requirements.

## Editing handoff

For the first stage, deliver separate rendered clips, a timing list and editable Remotion sources. Identify the scene and approved version associated with each delivered clip, and retain its timing basis and data/source evidence. The editor imports and places the clips manually in Resolve. Do not make automatic timeline assembly a first-stage requirement.

Deliver graphics clips without embedded voice-over. The original narration remains a separate continuous track for editing, while Storyboard review uses the relevant interval alongside the scene preview. Include the selected, synchronized sound effects in the delivered clip.

For graphics over real footage or photographs, the primary delivered clip is the completed composition with graphics and the selected background combined. Do not automatically create an additional transparent graphics export. A separate transparent layer is produced only after an explicit request; it is not a required first-stage deliverable or acceptance criterion. Retained editable sources support later revisions and requested alternate exports.

An FCPXML handoff containing the voice-over and positioned graphics is a possible later stage, not a committed first-stage deliverable. The accepted initial encoding and sound handling are described in the consolidated architecture below; quality and mix need pilot validation.

### Composition profile

The first-stage output resolution is Full HD, 1920 by 1080 pixels. Use 30 frames per second as the default for a new editing project. When working with an existing editing project, use its confirmed frame rate instead. Carry one project composition profile into scene authoring and rendering rather than inferring it separately from each found clip.

## Scene sound effects

Sound effects are part of the first-stage graphics workflow. The specialist selects existing sounds that support the scene's visual events, aligns them to the animation and includes them in the finished composition. Assess their levels and timing against the separate narration during human review. This decision does not require model-based sound generation or background-music selection.

Reuse suitable project sounds before acquiring missing ones. Preserve each used sound file, its provenance and reuse conditions, and its timing and level with the scene version. Changing the effects or their mix produces a new version for review. Source access and acquisition routes and detailed audio settings still need technical design; no sound-source connector is established as implemented by this decision.

### Remotion sound collection

The preferred starting point for basic effects is the confirmed CC0 subset of [`@remotion/sfx`](https://www.remotion.dev/docs/sfx). Its [usage guide](https://www.remotion.dev/docs/audio/sfx) documents named sound imports and timed audio playback. The npm code is MIT, while each sound has its own license; do not apply the package-code license to every audio file.

The current effect cards identify `whip`, `whoosh`, `pageTurn`, `uiSwitch`, `mouseClick`, `shutterModern` and `shutterOld` as CC0; examples include [whoosh](https://www.remotion.dev/docs/sfx/whoosh#attribution) and [uiSwitch](https://www.remotion.dev/docs/sfx/ui-switch#attribution). Other exports are not automatically eligible: the current [ding card](https://www.remotion.dev/docs/sfx/ding#attribution), for example, does not establish a free license. Select effects according to both the scene's purpose and their recorded individual reuse terms.

The [package source](https://github.com/remotion-dev/remotion/blob/main/packages/sfx/src/index.ts) exports remote WAV URLs rather than embedding the audio files. For repeatable scene rendering and editable-source delivery, materialize each selected permitted sound in the private project, record its source, license and content hash, and refer to the saved asset using Remotion's [local-asset mechanism](https://www.remotion.dev/docs/assets). Pinning npm versions alone does not freeze audio bytes at remote URLs. This is the accepted technical route, not an installed package or tested audio-acquisition implementation.

### Researched sound-source references

These are access and licensing findings, not implemented acquisition routes or proof of editorial suitability. A locally imported sound collection lets the specialist select and synchronize assets without requiring automated access to every library website.

| Resource | Confirmed reference facts | Design implication |
|---|---|---|
| [`@remotion/sfx`](https://www.remotion.dev/docs/sfx) | Named remote audio URLs; MIT package code and individual sound licenses | Preferred basic-effects collection, restricted to suitable effects with confirmed terms; save the selected permitted WAV files locally |
| [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | 100 files under CC0, with a public free ZIP download; the [official FAQ](https://kenney.nl/support) confirms commercial use and no mandatory attribution | Candidate for a small local collection and reusable sources; no documented search API or blanket authorization for automated crawling has been established |
| [Sonniss GDC collection](https://sonniss.com/gameaudiogdc/) | Public bundles; the [bundle license](https://sonniss.com/gdc-bundle-license/) permits monetized videos and restricts redistribution of raw sounds | Candidate for local selection; preserve the license applicable to the download and do not bundle restricted raw assets in distributed templates |
| [Mixkit sound effects](https://mixkit.co/free-sound-effects/) | Free SFX have their own [license](https://mixkit.co/license/modal/sfxFree/); [Envato's policy](https://help.elements.envato.com/hc/en-us/articles/31035788503321-Acceptable-Use-Policy) includes Mixkit and restricts automated access without express authorization | Manual acquisition and local import, unless an authorized automated route is separately established |
| [Freesound](https://freesound.org/help/faq/) | Individual sounds have distinct licenses; the [API terms](https://freesound.org/docs/api/terms_of_use.html) allow free API use only for non-commercial purposes, with separate commercial arrangements | A sound's CC0 license does not itself grant free commercial API access; inspect both acquisition access and the sound's reuse conditions |

No sound files were acquired and none of these download routes has been live-validated for this workflow. Preserve required credits and redistribution limits separately from the decision to use an effect in a finished clip.

## Consolidated architecture

The human editor confirmed the editorial choices and this consolidated technical organization on 2026-10-10. Prepare the implementation specification without requiring the visual reference. Collect the reference when implementation work begins, before authoring the first scene's visual design. Design acceptance is not an implementation claim or an instruction to start coding.

### Agent work and executable modules

The managing agent works in the user's agent host and retains the scenario plan. It selects scenes, creates one assignment per scene, works through them sequentially and delegates explicitly requested revisions. Each specialist receives shared style and relevant narrative context, while its saved scene workspace preserves its own facts, sources, code and questions. Resume the scene's session when available; after host context is lost, reconstruct the same scene assignment from saved records instead of relying on agent memory alone.

Keep the executable interfaces small and organized around actual work:

| Module | Interface responsibility | Implementation contained inside |
|---|---|---|
| Narration alignment | Analyze a supplied recording and locate supplied scenario passages; return saved matches or explicit uncertainty | Inworld submission/polling, transcript reuse, ordered text matching and manual timing corrections |
| Graphics scenes | Record an assignment, save a version and inspect its work state | Scene identity, input validation, dependency fingerprints, evidence, staged work, requests and repair accounting |
| Remotion rendering | Render one saved scene version to a declared output profile; return verified artifacts or diagnostics | Optional Node worker, bundling, local assets, browser rendering and output verification |
| Storyboard review | Present versions, timing, sources and saved human decisions/requests | Existing review-page and local saved-review exchange, narration playback and stale-version checks |
| Clip delivery | Publish an approved version's clip, timing entry and editable sources | Readiness checks, permitted material use, artifact identity and delivery bookkeeping |

These are responsibilities, not a requirement to create five wrappers or a new service for each row. Reuse the existing Python CLI and project records where they already own the work. Remotion authoring and rendering use an optional Node module; installing its dependencies is needed for graphics commands rather than ordinary source searches. Pin compatible runtime versions and identical exact Remotion package versions in its dependency lockfile, and record the versions used by each rendered result. Select the supported runtime and render settings during implementation preparation and verify them on Windows.

The specialist produces authored sources and researched inputs. The CLI validates and stores those inputs, invokes the renderer and records results. The CLI does not become a resident LLM orchestration server, and the existing social-source queue is not repurposed as a general agent or paid-generation executor.

### Input and result contracts

An assignment carries a stable scene identity, original scenario anchors, exact narration, chapter context, visual purpose, shared style revision, composition profile, known facts and material references, timing basis and unresolved questions. One continuous on-screen occurrence receives its own timed assignment. The five pilot moments are five visual concepts; a recurring timeline can require several occurrences without joining distant narration or treating a revised version as a new scene.

The version record binds the authored code and properties, source data and evidence, local media/font/sound references, timing, sound cues and levels, authoring/template revision and render profile to immutable artifact identifiers and hashes. The result records the preview and clip, diagnostic outcome, pending questions and readiness for human review. Approval is a separate human decision tied to that version; a successful render does not grant approval.

### Narration matching

Normalize recognized and scenario text for matching while preserving the original text and word timestamps. Match passages in narrative order using neighboring text anchors and sequence similarity. Return competing matches, skipped or repeated passages and boundary evidence as uncertainty for review; never use Inworld's unpopulated confidence field as a score. Human timecode corrections are retained as explicit overrides for the matching recording and scenario revision.

Keep both precise narration times and derived scene-frame intervals in the project profile. Apply a documented rounding rule when converting seconds to frames, and derive animation duration from that interval. Estimated draft timing remains distinct from narration-based final timing. Similarity thresholds and boundary accuracy must be calibrated on the actual pilot, not declared reliable from the algorithm description.

Before a paid submission, persist its input fingerprint and intent; then retain the returned operation identity and result. On continuation, poll a known operation or reuse a completed transcript. An interrupted submission whose provider outcome is unknown is reported as unresolved rather than blindly resubmitted. This avoids promising an exactly-once billing guarantee that has not been established.

### Project storage and continuation

Extend the existing project manifest, journal and serialized-write contract with explicit graphics records. Graphics are not fake discovered candidates with invented providers or licenses. Existing candidate and catalog records retain their semantics; legacy projects without graphics must remain readable. New graphics writes and their saved snapshots need the same recoverable transaction guarantees as the current records.

The accepted private-project layout keeps authoring work under `brolls/graphics/<scene>/<version>/`, shared saved assets under `brolls/graphics/assets/`, and narration analysis under `brolls/narration/`. Use the existing `previews/`, `clips/` and `reviews/` routes for their corresponding artifacts and exchanges. Originals, media and workspaces remain outside the product source repository. Exact JSON schemas and validation rules are specified before implementation, not inferred by pretending the current candidate-only validation already supports graphics.

Record durable stages for assignment, research, authoring, rendering and readiness for review, alongside explicit waiting/error outcomes. Save stage results before moving on. A work-in-progress directory or video alone does not establish a completed version; publish a version's result only after its declared artifacts have been checked. Resume from the last verified stage, retaining repair counts and pending questions.

Dependency fingerprints cover the relevant narration and scenario anchors, accepted timing, style, data, local assets, authored code, template and render/runtime configuration. Change only the affected dependent work. Shared assets may be deduplicated by content hash, while each version retains its references and evidence. Reuse is based on these inputs and intact results, not merely a saved filename. Local rendering runs one scene at a time with explicit bounded worker settings selected for the machine; it does not launch additional parallel scene jobs.

### Rendering, sound and editing

Use MP4 with H.264 video and AAC sound as the accepted initial ready-clip profile, at Full HD and the shared project frame rate. Record explicit encoding settings and verify visual quality, decoding, duration, dimensions, frame rate and audio in the pilot's actual Resolve project. Avoid adding an automatic alternate master or transparent export. Editable sources and permitted referenced assets accompany the approved result.

Freeze changing external inputs locally before rendering: selected data, media, fonts and sounds need recorded bytes and provenance. The default basic sound route is local project assets plus the suitable CC0 subset of `@remotion/sfx`; acquire only needed missing effects and retain their individual terms. Sound cues carry local asset identity, scene-frame placement, duration/trim and gain. The specialist mixes them against the corresponding narration during preview; human review checks speech intelligibility and the finished mix for clipping. Detailed levels are scene choices assessed in the pilot, not a fixed universal gain.

Storyboard playback includes the correct VO interval with the scene's effects. The delivered clip contains effects and its selected visual background, without VO. Its timing list identifies original narration times, frame intervals, scene and approved version. Delivery remains blocked for an unresolved fact/timing/material-use question or missing human approval, even if a preview was successfully produced.

### Later capabilities

Later model-based image/video production can contribute explicitly identified generated assets with its own model, prompt, operation, cost and provenance records. Such assets can become scene inputs or separately reviewed clips in the same project workflow. Implement that production module when its stage begins; first-stage code needs clear asset kinds and version records rather than hypothetical provider factories or empty generation integrations.

HyperFrames adoption requires the starred assessment above, including an actual capability or workflow need after Remotion is established. Possible FCPXML with VO is an independent later delivery module. Neither change requires replacing scene identity, saved evidence, version-specific review or the managing agent's original scenario plan.

## Pilot basis

Use the full supplied Venezuela scenario to select five pilot moments across the narrative. The pilot should exercise both graphics templates and custom graphics scenes. The proposed coverage below defines editorial concepts; it does not establish source verification, final visual approval or renderer acceptance.

Collect the pilot's reference video when implementation work begins, before authoring the first scene's visual design. Its absence does not block the accepted architecture or preparation of the technical specification. The reference and the visual attributes to adopt are pending.

The reference determines palette, typography, composition, animation and sound direction, and therefore affects scene and template code. It may also reveal a need for particular assets, visual libraries or renderer performance settings. The accepted organization of planning, narration alignment, versioned state, rendering, review and delivery can be specified independently; assess any concrete additional visual requirements when the reference arrives.

| Scenario moment | Proposed scene | Authoring coverage |
|---|---|---|
| Chapter 1: oil reserves and poverty | Animated numeric comparison with distinct units, dates and sources | Numeric graphics template |
| Chapters 2-3: the Chavez era and transition to Maduro | Historical timeline with dated milestones | Timeline template |
| Chapter 4: Guyana and Essequibo | Regional map distinguishing the disputed territory from recognized borders | Geographic template |
| Chapter 8: extra-heavy crude and dilution | Schematic explanation of crude, diluent, mixing and transport | Custom explanatory scene |
| Chapter 9: Cuba, China and Russia | Animated relationship diagram distinguishing oil, investment and cooperation links | Custom relationship scene |

Treat scenario claims as supplied narrative until their sources and dates are recorded. Use real dates for the historical timeline, identify a disputed area clearly on the map, and describe schematic flows as conceptual rather than exact physical routes. Keep scenario originals and detailed private scene notes outside the source repository.

## Accepted pilot criteria

Accept the first stage on the five selected scenario moments, using actual operation and human review:

1. Graphics: the scenes reach the required reference-based visual style and receive human approval, with sources recorded for displayed facts.
2. Timing: locate scene intervals in the complete recorded narration and allow uncertain matches to be corrected.
3. Storyboard: demonstrate preview with narration and effects, revision requests, saved-version comparison and version-specific human approval.
4. Editing: render locally on Windows and demonstrate actual use in Resolve, with Full HD output at the project frame rate, sound effects embedded and narration separate.
5. Preservation: demonstrate continuation after interruption and reuse of unchanged completed results while retaining sources and versions.

These are accepted requirements, not completed acceptance evidence. Resolve import and editorial acceptance must be observed on the actual pilot rather than inferred from output-file creation alone.

## Confirmation and implementation preparation

The individual workflow choices and consolidated architecture are confirmed, including explicit chat activation of saved Storyboard revision requests. The architecture interview is complete. The editor has deferred the visual reference until the start of implementation work; it is not a prerequisite for preparing the technical specification. Implementation requires a subsequent implementation request.

The accepted [implementation specification](SPEC-MOTION-GRAPHICS.md) is published as [issue #52](https://github.com/kovr33k/get-brolls/issues/52) with `ready-for-agent`. It synthesizes this architecture and the confirmed public CLI/Storyboard testing approach. Publication is a specification outcome, not evidence that the product workflow is implemented or accepted in Resolve.

During implementation preparation, finalize the accepted specification's exact schema encoding, command interfaces, compatible dependency versions, frame conversion convention, matching criteria, renderer limits and artifact checks before coding the affected routes. Keep reference-dependent visual choices pending until work begins. These are bounded engineering details within the accepted contract, not evidence that the design already works. Calibrate timing, quality and sound on the pilot; acceptance remains the observed five-moment workflow and actual Resolve use described above.

## Existing domain references

Use the [domain glossary](../CONTEXT.md#motion-graphics-language) and preserve the existing [fragment search decisions](adr/0001-fragment-catalog-search-chain.md) when defining how graphics relate to source discovery. This draft does not revise the catalog-search contract.

## Initial visual direction — 2026-10-10

Initial visual authoring may begin with a proposed documentary style without a supplied external reference. Save that direction as an explicit proposed style revision and show its actual rendered preview for editorial feedback. This permits the first scene's authoring; it does not infer human approval or freeze the visual direction for all later scenes. An external reference may refine the style later, with affected versions reviewed again.
