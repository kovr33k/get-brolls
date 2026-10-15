---
type: specification
status: accepted
created: 2026-10-16
updated: 2026-10-16
tags: [get-brolls, ai-generation, storyboard, narration, integration]
---

# AI scenes for scenario beats

This consolidated first-version contract was accepted by the editor on 2026-10-16. Individual product choices and the final shared-understanding confirmation are recorded in the [design interview](DESIGN-AI-GENERATION.md). Implementation proceeds under repository workflows; design acceptance is not a blanket authorization for paid work or an unspecified live-generation pilot.

Use the terms in [CONTEXT.md](../CONTEXT.md). Existing search behavior remains governed by [ADR-0001](adr/0001-fragment-catalog-search-chain.md); this module does not introduce recursive subdivision into catalog search or change its three-option rules.

## Intended result

After analyzing the original scenario, the managing agent plans meaningful narrative beats and routes visual work to source-based B-roll, Remotion graphics or AI production. AI can be an independent editorial approach, without first exhausting source searches. Generated material remains identified as generated rather than documentary evidence.

Every AI beat receives three distinct scene alternatives in the same Storyboard used for the project. The editor selects one alternative for each beat they want to produce and may add a comment. Selection, instructions and results remain tied to that beat; the editor need not finish every beat before working on a selected one.

## Accepted production workflow

### Alternatives and selection

- Start in **AI economy mode**: show three textual scene alternatives. Generate an image only for the selected alternative, incorporating the editor's optional comment.
- Provide **AI image comparison mode**: prepare three generated images for visual selection. Keep unselected images available; selection advances one treatment rather than animating all three.
- The three alternatives must offer meaningfully different visual treatments. Three copies with minor phrasing changes do not satisfy the purpose.
- Both modes use the agreed project visual style. The managing agent proposes the style, the editor corrects it and may supply references. Economy mode changes the initial comparison format, not the promised final quality or billing route.
- Do not confuse three alternative treatments with consecutive shots in a sequence. A selected treatment may later need several clips to cover its narration interval.

### Stills, video and sound

- The main path is selected concept → generated still → explicit approval of the exact still → video from that still → review of the resulting video/sequence.
- Choosing a textual proposal cannot approve an image that does not exist yet. Image selection, still approval and video approval remain distinct meanings even if an explicit UI action combines related steps.
- Before narration is recorded, prepare and approve stills. Generate video only after recorded narration is available and the intended interval is established. Estimated-duration AI video before recording is outside this accepted workflow.
- Deliver visual coverage for the intended narration interval, using several clips when needed. Retain the ordered clips and their placement in the interval. If more source stills are needed, each requires approval before its animation; initial alternative selection is not blanket approval of future images.
- Suitable atmosphere and effects may accompany the clips. Music and speech require an explicit request. Project narration remains separate from delivered clip audio.
- Review the result rather than treating model completion as acceptance. The editor can revise or reject a result; automatic checks never register human approval.

### Prompts and references

- A normal prompt can request a correction, refinement or entirely different scene. A separate routine edit-versus-regenerate selector is unnecessary.
- Files are optional. Support both image and video references in the first version, with intended use expressed in the prompt, for example appearance from an image and camera motion from a video.
- Reference analysis is separate from provider input support. Inspect the actual supplied media and apply the requested characteristics; do not claim every generation provider accepts raw video, or silently add direct video-to-video generation as a required route.
- Instructions may identify a relevant video interval in text. Inspect the requested interval; ask about material ambiguity rather than silently choosing an arbitrary beginning or truncation.
- References and prompts belong to the selected beat/result. Revisions preserve earlier versions and the actual context used for each version.

### Storyboard actions

- Launch follow-up image generation, revision and animation from the Storyboard. No subsequent chat command is required to activate saved work.
- Show progress, completion and errors in place. A new result must appear without a manual page reload, while retaining the selected beat and unsent comments/files.
- Keep selected-alternative comments available before generation. After a result exists, retain the exact version targeted by a revision; do not silently retarget it to a newer result.
- An explicit generation/apply action starts work. Merely opening the page, typing, choosing a file or changing a selection does not generate media.
- Keep the primary review surface focused on alternatives, selected scene, prompt/files, result and next action. Put provider/job diagnostics and provenance in a collapsed Details area.

### Access, confirmation and corrections

- Initial routes are GPT and Grok subscriptions plus OpenRouter API. Additional providers must be addable without changing the beat, review and delivery model.
- Prefer a suitable subscription route. Missing capability, exhausted quota or a failed subscription login does not authorize a paid fallback.
- Confirm every paid OpenRouter generation launch in the Storyboard. Bind confirmation to the actual planned inputs and outputs; it is not a project-wide grant. Display the available cost estimate and distinguish an unknown estimate from a quoted price.
- Where a launch explicitly covers three image outputs, show that scope. A later separate job, changed launch or corrective paid generation requires its own matching confirmation.
- If the agent observes an obvious defect, permit at most one additional corrective generation for the editor-requested operation, within authorized limits. Retain the attempt history. A paid API correction still requires confirmation, and an approved still cannot be silently replaced during video correction.
- Download recovery and status checks are not permission to submit another generation. A network-uncertain submission must be reconciled before another potentially billable request is made.

## Shared-workflow integration

These integration choices accompany the accepted product decisions. They are not claims that the current code already supports AI media.

1. Reuse original scenario anchors, existing recorded-narration analysis/alignment and the project's aspect/frame-rate profile. Do not rewrite narration, invent factual claims or add a second full-script fact audit as a prerequisite for AI production.
2. Keep generated assets and their versions in the existing private project workflow, alongside discovered footage and graphics. Store original provider media, submitted input derivatives, prompts, references and their identities; do not disguise generated assets as source-catalog candidates.
3. Reuse retained-version comparison and exact-version human decisions. A change to one beat does not invalidate unrelated completed beats. Relevant changes to a selected image, scene instruction, narration interval, clip ordering or sound require review of the affected descendant result.
4. Keep references and unrelated instructions active across revisions until replaced or canceled. A later instruction changes its stated scope; a beat-local attachment does not silently rewrite project-wide style. Preserve the historical context separately from the currently active one.
5. Present sequence preview with its corresponding narration interval and sound, then deliver the approved video without embedding that narration. Reuse the existing timing/placement handoff for Resolve and preserve links to the selected beat and approved versions.
6. Prefer the shared delivery profile where the selected route actually supports it. Report real dimensions, frame rate and duration. Do not present upscaling as native Full HD; an unmet required profile or unresolved narration match remains visible instead of being declared ready.

## Provider feasibility and boundary

The [provider-route audit](research/AI-SUBSCRIPTION-ROUTES.md) contains dated primary sources and separates published code from live media evidence.

| Route | First-version role | Current evidence boundary |
|---|---|---|
| Native Codex with ChatGPT login | Generate and edit stills through a bounded local native tool operation | Documented/source-level worker path; actual account/media/artifact handoff not validated |
| Native Grok with OAuth | Images, edits and animation of the approved still, when available through the actual installed tools/account | Public media tools and OAuth routing found; installed-version parity and actual outputs not validated |
| OpenRouter API | Explicitly confirmed image/video operations supported by the selected model | Documented endpoints; actual model/account access and quality not validated |

Do not substitute third-party ChatGPT OAuth text access for native image-tool availability. Do not promise a GPT subscription video operation: no supported native path was established by the audit. Prevent Grok's subscription route from silently using a static API key.

Native Codex generation is currently documented with GPT Image 2, while the API lists GPT Image 2.5 models. Neither an OAuth login nor an API catalog entry proves the latest API model is available through subscription automation. The [subscription-capacity check](research/GPT-IMAGE-SUBSCRIPTION-LIMITS.md) does not establish a fixed image count.

The adapter boundary must describe actual operations, auth/billing route, accepted reference types and output limits. Missing capability produces a truthful unsupported/waiting result, not a nominal success or an unapproved provider switch. Adding a provider should reuse the same production, approval and recovery records.

## Engineering contract to preserve during implementation

- Represent every AI generation job with a stable identity and frozen beat/alternative, prompt, reference/input hashes, model/access route, requested output and applicable confirmation. Save the job before starting provider work.
- Keep submission, provider processing, media retrieval and reviewable completion distinct. Process success, a text reply or a remote job ID is insufficient: require the intended, locally saved and decodable media artifact.
- Use the exact approved still as the animation input. Record content-preserving format conversions as traceable derivatives; semantic image changes require a new approval. Do not use a generic tool recipe that regenerates its own starting image unnoticed.
- A local worker may make a bounded native provider turn; the desktop chat need not remain active. The worker executes the frozen production request rather than becoming an independent scene-authoring hierarchy.
- Serialize project state changes with the existing locking/journal rules. Keep original files, durable attempt counts and completed results across interruption. Reconcile unfinished work on explicit recovery without recharging for an already generated result.
- Repeated browser submissions must resolve to the intended existing job or a clearly explicit new request. An in-flight job keeps its frozen inputs when the editor drafts a later prompt.
- Status/result refresh is read-only and must not trigger recovery or new generations. Preserve the existing `status` command's no-write/no-exclusive-lock contract.
- Extend the local authenticated server boundary without exposing keys, OAuth tokens, private narration, signed URLs or arbitrary filesystem/command access. Keep media/projects outside the product source tree.
- Without the local server, retain supported portable review behavior and clearly disable actions requiring uploads or live provider jobs. Do not pretend browser-selected files are already saved project inputs.

Exact schemas, endpoint names and worker transport are implementation preparation details. Verify them against the selected installed provider route before building the affected integration; this document does not invent existing CLI commands or announce those endpoints as implemented.

## Accepted workflow example

Use a hypothetical scenario beat: **"The resource is running out."** The agent routes it to AI and shows, in economy mode:

1. An almost empty reservoir, with the former waterline visible on its walls.
2. A single drop gathering at the end of a large industrial pipe.
3. A warehouse with one remaining container and rows of empty storage spaces.

The editor selects option 2 and comments: **"Close-up, night lighting; show no people or labels."** Generating produces one image for that request, not images for the other two descriptions. If image comparison mode is selected instead, the initial choice is between three generated images.

If the image needs a change, the editor adds a prompt and optionally an image/video reference and presses Apply in the Storyboard. The new result appears there as a retained version. Once the exact still is approved and narration timing is available, the editor starts video production; an API route requests confirmation for that concrete paid launch. Review includes the intended interval and sound. An accepted result proceeds through the shared Resolve handoff; unselected alternatives are not automatically animated.

This example explains the workflow; it is not actual scenario content, a generation request or an editorial approval.

## Verification and pilot acceptance

Automated tests use synthetic media and mocked providers. Cover both modes and selection/comments, image/video attachments, exact-input approval binding, paid-launch confirmation, duplicate submission, one-correction accounting, unknown submission outcome and download recovery. Include compatibility checks for existing review/state and the read-only status contract. Verify actual UI behavior in a browser: direct launch, progress/result updates, switching beats and retaining unsent edits, errors and version comparison.

Define the concrete paid scope and media before a bounded live pilot. At minimum, establish:

1. A GPT subscription still and edit with actual saved artifact handoff; keep account/model/route evidence distinct from documentation.
2. Grok subscription animation from the exact approved still, with actual dimensions, duration, audio and auth route recorded.
3. An explicitly confirmed OpenRouter operation for each claimed initial API media route; verify retrieval of the same result after an interrupted download without a new generation.
4. An economy-mode beat, a three-image comparison beat, a reference-led revision, and a narration interval requiring several clips. Inspect actual image/video references instead of testing only upload metadata.
5. Human review of the retained results and real use of the approved files in Resolve, including timing, media online, decoding, audio and any profile shortfall.

Evidence is reported separately as documentation/source inspection, automated tests, browser verification, live provider media and human/Resolve acceptance. A green test suite, generated MP4 or registered adapter alone does not close the pilot. No paid or subscription generation was run during this design interview.
