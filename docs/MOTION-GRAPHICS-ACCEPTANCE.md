---
type: documentation
status: current
created: 2026-10-13
updated: 2026-10-13
tags: [get-brolls, graphics, acceptance, evidence]
---

# Numeric graphics acceptance — issue #53

This checkpoint covers [#53](https://github.com/kovr33k/get-brolls/issues/53): register a graphics assignment, render a numeric composition locally on Windows, and review the verified saved version in the shared Storyboard. The [specification](SPEC-MOTION-GRAPHICS.md) and [operational guide](GUIDE.md#graphics) describe the wider workflow. Human approval, delivery and Resolve acceptance belong to subsequent tickets.

## Criterion evidence

The numbers follow the sixteen acceptance criteria in #53. Code and tests are repository-relative, reproducible entry points; private projects and media are excluded from distribution.

| Criterion | Implementation and verification |
|---|---|
| 1. Assignment identity and original context | `graphics.assign_command` persists and returns scene/occurrence IDs, original narration, chapter context, purpose, anchors, references, questions, proposals, style revision, profile and timing. `test_preserves_original_multiline_narration_and_chapter_context` and `test_scene_identity_is_independent_of_template` verify retained inputs and distinct identities. |
| 2. Estimated and explicit timing | `default_profile`, `_profile_for_write` and `_timing_from_args` preserve Full HD, default 30 fps or explicitly confirmed project fps. Estimated timing has duration only; explicit intervals use nonnegative half-up frame rounding. `test_estimated_timing_rejects_start_and_existing_project_needs_confirm_fps` and `test_public_review_shows_zero_anchor_and_explicit_interval` cover both modes. The draft badge and exact duration/frame count remain in Storyboard Details. |
| 3. Repeated occurrences and versions | Occurrences are independently keyed without a per-chapter cap; version records retain their parent and scene binding. Additional-scene proposals remain assignment data. Original-context, scene-identity and immutable-render tests exercise this distinction. |
| 4. Pending cards beside candidates | `graphics.storyboard_section` and `rendering.render` add graphics cards to the existing review page. `test_assign_command_does_not_invent_candidates` and `test_candidate_review_stays_intact_with_graphics` check pending graphics and unchanged candidate semantics. |
| 5. Compatible recoverable records | Ledger validation accepts legacy projects without graphics and validates new graphics records without resetting history. `test_legacy_manifest_without_graphics_still_validates`, malformed-version/style tests and interrupted-freeze tests cover compatibility and failure handling. |
| 6. Read-only status | `graphics.graphics_status` reports persisted assignments through the existing `status` route, using `recover=False`. `test_status_reports_pending_graphics_without_writing_or_recovering` checks the unchanged project tree and pending journal; `test_status_answers_while_another_command_holds_the_lock` verifies the shared route's lock-independent operation. |
| 7. Public CLI, documentation and regressions | The guide documents assignment, status, setup and rendering commands. `test_graphics.py`, `test_graphics_review.py`, `test_storyboard.py` and server tests exercise the public CLI and mixed/graphics-only pages with synthetic inputs. |
| 8. Reference timing and authoring boundary | The guide and [production workflow](../references/graphics-workflow.md) collect the reference/style choice at implementation start and retain an explicit decision to use the proposed style without an external reference. No model image/video generation integration is introduced. |
| 9. Optional setup and exact pins | The explicit setup is `npm ci --ignore-scripts --prefix scripts/graphics`, followed by `graphics-doctor --prepare-browser`; `graphics-doctor` reports runtime/browser prerequisites. `scripts/graphics/package.json` and its lock pin Remotion, renderer and bundler to the same exact version. Optional-runtime tests retain collection/help/provider behavior without Remotion. Rendering does not install dependencies or download a browser/font. |
| 10. Shared style recorded at work start | Style revisions preserve the proposed documentary palette, typography, motion and the recorded reference/style decision. `test_estimated_duration_only_and_style_history` checks revision history; frozen versions retain their own style snapshot. Choosing a working style does not approve a rendered scene. |
| 11. Validated sequential render | `graphics.render_command` validates the composition/profile, freezes the job and invokes one local render with bounded concurrency. The frozen worker selects the declared composition and prepared browser. Missing-runtime, composition-selection and failed-worker tests check useful diagnostics. |
| 12. Actual verified MP4 | Real Windows Remotion renders produced Full HD H.264/yuv420p clips at 30 fps. FFprobe counted decoded frames and checked both reported frame rates; FFmpeg decoded with `-xerror`. The retained numeric sample rechecked on 2026-10-13 measures 1920×1080, 30/1 fps, 161 frames and 5.366667 s of video with no decode errors. Earlier synthetic estimated/explicit renders retain their timing modes. |
| 13. Complete only after verification | Staging, frozen source/props/style/runtime fingerprints, verified artifacts and publication precede the complete record. `test_freeze_oserror_marks_incomplete_and_does_not_reuse_identity`, failed-worker and artifact-mutation tests cover incomplete outputs and integrity. |
| 14. Immutable versions without inferred approval | Version allocation skips occupied/orphan destinations. Later renders retain earlier bytes, frozen assignments, source hashes and identities. `test_orphan_version_dir_is_skipped_not_reused`, `test_saved_version_stays_paired_with_frozen_assignment` and `test_stub_render_publishes_immutable_preview_and_keeps_failed_version` verify this behavior. |
| 15. Actual preview and frozen context | Completed cards expose their saved video, original narration, anchor/timing details and uniform version controls. Mixed-board/UI tests verify frozen context, estimated versus explicit timing, paired VO state and absence of automatic approval. |
| 16. CLI-to-Storyboard and real Windows path | Synthetic public-CLI cycles and actual local Remotion renders cover registration, freeze, verification and Storyboard playback. Browser observations cover playback to the end, version selection/comparison and 375 px layout without horizontal overflow. Missing prerequisites remain errors, not fabricated success. |

## Verification and limits

On 2026-10-13, 89 focused tests covered graphics registration/rendering, renderer selection, graphics review, Storyboard and media-range serving. Eighty-eight passed initially; one stale copy-specific assertion was updated to verify the current draft badge, duration/frame count and public timing basis, then passed separately. No product/runtime change was needed for that repair. The complete Windows CI result for the final submitted tree is recorded on the integration PR and is required before merge.

Existing real render, immutable-version and browser evidence is retained privately. Reviewing a page, rendering a clip or passing tests does not record a human scene decision. No operational scene approval or Resolve acceptance is claimed here. Narration-bearing tests use the available recordings only; no future recordings or additional paid requests are prerequisites for #53. Later ticket acceptance is assessed separately.
