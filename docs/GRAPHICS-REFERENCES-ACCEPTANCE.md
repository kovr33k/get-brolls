---
type: documentation
status: current
created: 2026-10-16
updated: 2026-10-18
tags: [get-brolls, graphics, references, acceptance, windows]
---

# Storyboard reference acceptance checkpoint

This checkpoint maps all **55 user stories** and **13 acceptance criteria** of [the accepted contract #74](https://github.com/kovr33k/get-brolls/issues/74) to the implemented reference workflow and its evidence. It supports [final acceptance #79](https://github.com/kovr33k/get-brolls/issues/79); it does not close that ticket or its parent. The implementation is the combined 2.16.0 active/shared-context and recovery branch, following the integrated 2.14.0 image and 2.15.0 mixed-reference slices.

**The agreed human visual acceptance is complete; integration remains pending.** A real image-guided scene and its following text-only revision received separate exact-version chat approvals. On 2026-10-18 the acceptance scope was explicitly amended to remove the additional human video-reference demonstration. Video transport, temporal selection, inclusion and retained context remain technically verified; cinematic video-style correspondence has no human acceptance claim. Automated success, native rendering and editorial approval retain their separate evidence boundaries. The separate AI-generation work is outside this checkpoint; its eventual integration needs checks for the actual combined revision.

## Evidence and revision boundaries

The complete local Windows check script passed **1,635 tests, 32 skips, no failures, in 895.506 seconds**. Required [Windows CI](https://github.com/kovr33k/get-brolls/actions/runs/38971486563) subsequently passed **1,635 tests, 26 skips, no failures, in 1,245.798 seconds** for executable revision `7e54263`; its verification artifact matches the tested tree. A later documentation-only revision still requires its own final PR check before integration. Lint, formatting, types, generated skill mirror and relative links passed. Version coherence, JavaScript syntax and the final **24-test Storyboard** recheck passed. The required **Windows checks** must also be green for the PR revision actually being integrated; the PR check record is the authority for that revision. Existing passing evidence is reused only for unchanged code, dependencies, configuration and relevant artifacts. Documentation-only additions retain the executable evidence and receive fresh link/frontmatter checks.

The following evidence keys identify observable journeys, rather than a count of helper calls:

| Key | Evidence |
|---|---|
| A | [Image HTTP/CLI journeys](../tests/test_graphics_references.py): pre-render save/reopen/import/apply/render, exact-version revisions, stable identity, corrupted bytes, invalid sessions and paths. |
| M | [Mixed-reference journeys](../tests/test_graphics_mixed_references.py): initial and revision inputs, duplicate filenames, actual temporal evidence, intervals/whole clips, limits, explicit inclusion and editable-delivery gates. |
| C | [Active/shared-context journeys](../tests/test_graphics_reference_context.py): retained files/instructions, text-only reuse, remove/replace/empty sets, fixed subsets/exceptions, handoff and independent outcomes. |
| R | [Recovery journeys](../tests/test_graphics_reference_recovery.py): partial/malformed transfers, metadata faults, lost acknowledgements, journals, locks, fixed shared scope plus composition, verified render reuse and unchanged narration operations. |
| U | [Review regressions](../tests/test_graphics_review.py), [Storyboard tests](../tests/test_storyboard.py) and the [actual JavaScript harness](../tests/fixtures/storyboard_graphics.cjs): existing decisions, historical versions, drafts, active/historical files, print/export, fallback, navigation and blocked-reference feedback. |
| S | [Server regressions](../tests/test_serve.py): local origin/session boundaries, confined publication, private files, range/HTTP behavior and existing ordinary saves. |
| Q | [Graphics audio tests](../tests/test_graphics_audio.py) and U: frozen audio inputs, original source/local clocks, paired review media and compatible controls. These do not claim new human listening or Resolve acceptance. |
| B | Actual local-browser observations recorded in [QUALITY](QUALITY.md#mixed-imagevideo-references--2026-10-16-2150-candidate), [active/shared context](QUALITY.md#active-and-shared-reference-instructions--2026-10-16-2160-candidate) and [recovery](QUALITY.md#interrupted-reference-work--2026-10-16-2160-candidate). Native multiple/single-file pickers, playback, save/retry, remove/replace, historical views and desktop/375-pixel layouts were observed. |
| N | Three native locked-runtime Remotion previews: image-guided initial authoring, a revision bound to that version with explicit original video interval **3–5 seconds**, and a text-only descendant retaining both references and the same inclusion. Originals, prompts, temporal sheet, analyses and old-version hashes are retained in a separate synthetic project. These are technical evidence without human visual approval. |
| H | A separate real-editor project: the image-guided draft v2 and its text-only revision v3 received distinct explicit chat approvals. Native saved outputs are H.264, 1920×1080, 30 fps and ten seconds, strictly decoded and measured. The original image, analysis basis, narration text, prior version bytes and approval history remain retained. Private prompts, source media and statements stay outside distribution. |

The agreed principal automated journey is M's `test_initial_and_revision_mixed_save_reopen_temporal_analysis_frozen_history`: actual local HTTP transfer/save, reopened review data, CLI import and explicit processing, fixture-rendered versions and intact history. A covers the compatible single-image route. C adds active instruction carryover. R's `test_shared_composition_render_recovery_reuses_fixed_results_and_reports_changed_evidence` exercises the combined inclusion/shared-scope/recovery path. A fixture renderer is explicitly used for these automatic contracts; N is separate native-render evidence.

## User-story traceability

“Technical” below means the stated behavior has automated and/or browser evidence. H records the completed image/text visual assessment. Video motion/style quality remains a technical-only boundary under the explicitly amended acceptance scope.

| Story | Implemented behavior and evidence | Boundary |
|---|---|---|
| 1 | Before-first-render reference input, assignment-bound: A, M, B, N, H. | Technical; real image-guided draft accepted in H. |
| 2 | Reference-backed changes to the first saved result: A, M, B, N, H. | Technical; real text-only follow-up accepted in H. |
| 3 | Later current versions retain the same editing controls: C, U, B. Historical views remain bound/read-only until explicit version selection. | Technical. |
| 4 | Actual PNG/JPEG image admission, thumbnails and frozen originals: A, M, B, H. | Adopted image-guided appearance accepted in H. |
| 5 | Actual MP4/H.264 admission, playback and temporal inspection: M, B. | Technical; additional human video-style assessment removed from the acceptance gate. |
| 6 | Up to eight files in one request: M, U, B. | Technical. |
| 7 | One required original prompt for the attachment set: A, M, U, B. | Technical. |
| 8 | Stable R1–R8 labels and duplicate display names: M, U, B. | Technical. |
| 9 | Prompt-directed roles, without a role questionnaire: A, M, C, U. | Technical; actual interpretation is recorded explicitly. |
| 10 | Original interval wording and resolved source-clock bounds: M, R, N. | Technical. |
| 11 | Inspection evidence and inclusion retain the requested 3–5-second interval: M, R, N. | Technically verified in saved native output; no human video-style approval claimed. |
| 12 | Explicit whole-clip inspection, including a supported clip longer than one minute: M. | Technical; finite validation/sampling limits remain explicit. |
| 13 | Bounded bytes/dimensions/rates, clear rejection and no silent trim: A, M, R. | Technical; unsupported ranges require clarification or a new input. |
| 14 | Design-only reference bytes stay outside composition/delivery: A, M, N. | Technical. |
| 15 | Explicit actual inclusion uses selected local media and existing gates: M, C, R, N. | Technically verified; N remains an unapproved synthetic sample. |
| 16 | Original narration, facts, units and meaning are retained in frozen assignments: A, M, C, N. | Technical; editor can inspect the retained twelve-unit example. |
| 17 | Reference editing opens on demand: U, B. | Technical/browser. |
| 18 | Planned rows have no fabricated rendered version/approval: A, M, U, B. | Technical/browser. |
| 19 | Project-local copies survive moving external originals: A, M. | Technical. |
| 20 | Attachments and original prompts survive reopening Storyboard: A, M, C, U, B. | Technical/browser. |
| 21 | Failed transfer/save is visible and cannot claim selected bytes are ready: M, R, U, B. | Technical/browser. |
| 22 | Identical lost-response retry reuses one durable submission: R, B. | Technical/browser. |
| 23 | A blank prompt is refused while selected files/draft remain available: A, M, U, B. | Technical/browser. |
| 24 | Save/import stay idle until chat activation: A, M, C, R, U. | Technical; no implicit semantic/paid/render job. |
| 25 | Existing chat instruction activates analysis/authoring from saved context: A, M, C, N; GUIDE workflow. | Technical/workflow. |
| 26 | Analysis proceeds to a new version without a routine analysis-approval step: A, M, C, R, N. | Technical; independent media-selection/use gates remain. |
| 27 | Clarification is reserved for material ambiguity in actual roles, intervals or scope: M, C; GUIDE workflow. | Product workflow; no automatic semantic interpretation is claimed. |
| 28 | Actual analysis, limitations and effective instructions explain adopted characteristics: A, M, C, N, H. | Real image-guided draft and text revision accepted in H. |
| 29 | Text-only follow-up retains files and original analysis basis: C, R, N, H. | Technical and real accepted follow-up. |
| 30 | Unrelated earlier instructions retain label/hash bindings: C, U, N. | Technical; semantic resolution is explicitly authored. |
| 31 | Effective instructions resolve the new prompt without rigid local/shared priority: C. | Technical; automated cases use actual explicit resolutions. |
| 32 | Active future references differ from historical frozen inputs: C, U, B. | Technical/browser. |
| 33 | Individual removal updates the future reference set: C, U, B. | Technical/browser. |
| 34 | Individual replacement retains the label while binding new bytes: C, U, B. | Technical/browser. |
| 35 | Removal/replacement/save do not launch production: C, U, B. | Technical/browser. |
| 36 | Previous versions retain their reference contexts and bytes: A, M, C, N. | Technical. |
| 37 | Scene-local scope leaves other occurrences unchanged: C, U. | Technical. |
| 38 | Explicit wider scope records concrete scene targets before production: C, R, B. | Technical; unresolved scope remains visible. |
| 39 | Prompt-specific scope and exceptions are saved per target: C, R, B. | Technical; actual editorial intent is not guessed. |
| 40 | Unaffected scenes and approvals remain unchanged: C, U. | Technical. |
| 41 | Original assignment/version/context binding survives stale edits and replay: A, M, C, R, U. | Technical. |
| 42 | Retained versions support comparison and navigation: A, C, U, B, N, H. | Technical/browser; real revision accepted in H with its predecessor retained. |
| 43 | New versions have their own approval state: A, C, U, N, H. | H has separate exact-version approvals; N remains unapproved. |
| 44 | Existing text-only, reference-free and singular-image flows remain compatible: A, C, U. | Technical. |
| 45 | Portable ordinary JSON review/import remains available: A, U, S. | Technical. |
| 46 | Direct-file HTML cannot claim unsaved binary transfer: U, S. | Technical/interface regression. |
| 47 | Status/handoff expose original prompts, targets, files and processing state: A, C, R. | Technical; read-only status performs no recovery. |
| 48 | Reference-only versus explicitly included media remains distinct: M, C, R, N. | Technical; reuse rights do not follow from upload. |
| 49 | Hash/size/path/evidence checks refuse changed or missing originals: A, M, C, R, B. | Technical/browser. |
| 50 | Per-file analysis, original interval and effective instructions remain reconstructable: M, C, R, N. | Technical. |
| 51 | Save/import/request continuation are idempotent for intact matching work: A, C, R, B. | Technical/browser. |
| 52 | Project locks and journal recovery preserve prior state/events: R, S. | Technical. |
| 53 | Confined paths, bounded bodies and current-session local access: A, M, R, S. | Technical; staged/private files are not ready/served references. |
| 54 | Public local-server/review/CLI boundary journeys, rather than isolated helper-only assertions: A, M, C, R. | Technical. |
| 55 | Actual native previews and their references are retained: N, H. | **Agreed image/text human assessment complete; additional video assessment explicitly removed.** |

## Parent acceptance criteria

| Criterion | Evidence | Remaining acceptance boundary |
|---|---|---|
| 1. Planned initial authoring, real bytes/prompt, no invented review | A, M, B, N, H. | Real image-guided draft accepted in H. |
| 2. Multiple files/equal names, durable reopen/context | M, C, B. | No unresolved technical gate. |
| 3. Independent copies; changed/missing bytes detected | A, M, C, R, B. | Preserve originals rather than silently replace them. |
| 4. Exact reviewed version and distinct file/base identity | A, M, C, R, U. | No silent retarget during later integration. |
| 5. Requested interval/whole clip; no arbitrary minute limit | M, R, N. | Clarify genuinely ambiguous prose; sparse samples do not prove fine motion. |
| 6. Style-only separation and explicit inclusion/reuse gates | M, C, R, N. | Technically verified; video example has no human visual approval claim. |
| 7. Text-only retained direction, remove/replace, immutable history | C, U, B, N, H. | Real text-only follow-up accepted; original reference/history retained. |
| 8. Local versus fixed shared scope/explicit exceptions | C, R, B. | Independent shared targets remain incomplete/conflicted when appropriate. |
| 9. Non-processing actions remain idle | A, M, C, R, U. | Technical validation/decoding is not semantic authoring. |
| 10. Incomplete transfers/publication and safe idempotent retry | R, B. | Corrupt evidence waits for explicit recovery. |
| 11. New frozen result and independent exact-version approval | A, M, C, R, U, N, H. | **H has separate exact-version approvals; N remains unapproved.** |
| 12. Existing decisions, fallback, navigation, print and paired narration | U, S, Q. | Established supplied-narration/Resolve acceptance remains bounded to its original files. |
| 13. Main journey, browser, recovery, final Windows CI and visual result | A, M, C, R, U, B, N, H; required PR checks. | **Agreed visual assessment complete; current required PR check and integration remain.** |

## Native preview assessment packet

The retained synthetic project has this exact sequence:

1. **v1 — REFERENCE INITIAL:** adopt R1's dark panel, large paper numerals, amber accents and separate lower text blocks. The reference is a geometric palette/layout sketch, without a real typeface or animation. The scene keeps its original twelve units and narration text; the sketch itself is not a composition asset.
2. **v2 — MIXED REFERENCE REVISION:** revise v1, retain R1 and place the actual R2 source interval **3–5 seconds** behind the graphics. The original clip is red for its first three seconds and blue afterwards. The selected interval is uniformly blue, so this case proves actual inclusion/source-clock selection; it does not claim sophisticated motion imitation.
3. **v3 — TEXT FOLLOW-UP:** change only the label to **TEXT FOLLOW-UP** while retaining the active references, palette, original data/narration and the same included interval. Old version files remain unchanged.

All three previews use native Remotion, **1920×1080, H.264, 30 fps, two seconds**. Each output is strictly decoded, measured and retained with its hash. No fixture renderer, paid semantic/generation provider or new human approval is used for this packet. There is no recorded VO in these synthetic examples; narration text is retained, and Q covers the unchanged audio contracts separately.

This synthetic packet remains technical evidence. The agreed human assessment is recorded separately in H; no approval is inherited by these samples. The additional human video-reference demonstration was explicitly removed from the acceptance gate on 2026-10-18. Fine-motion correspondence has not been human-assessed. Main integration remains subject to the current required PR check and the maintainer's integration decision.

## Human visual acceptance and scope amendment — 2026-10-18

H used an actual supplied image as design guidance. The initial accepted version v2 adopted the requested appearance. A subsequent ordinary text request changed part of the scene. The resulting v3 retained the original reference and analysis basis, overall direction, narration text and previous versions. Both results received their own explicit chat approval through the public graphics approval command. The text-only request is processed with no reference-work issues.

The accepted previews have estimated timing and no recorded narration. Their approval establishes visual correspondence for these exact drafts; it does not establish a historical-fact audit, narration alignment, delivery readiness or a new Resolve observation. Originals, source permissions, frozen inputs, hashes and exact approval records remain in the private project.

The acceptance amendment removes only the additional human video-reference example. All implemented video, mixed-reference, interval, inclusion, shared-scope, recovery and compatibility requirements remain in scope and retain their automated/browser/native evidence. No unviewed synthetic preview is marked human-approved.

## Operational documentation

The canonical operating instructions are the [reference guide](GUIDE.md#saved-image-references), [shared scope](GUIDE.md#shared-reference-changes), [interruption recovery](GUIDE.md#recover-interrupted-reference-work) and [sequential authoring workflow](../references/graphics-workflow.md). [QUALITY](QUALITY.md) distinguishes automated, native/browser, provider and human evidence. The current [CHANGELOG](../CHANGELOG.md) records the 2.16.0 behavior. Test originals, runtime output and private machine paths are retained outside the distributed source.
