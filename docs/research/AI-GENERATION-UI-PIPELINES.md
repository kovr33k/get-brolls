---
type: research
status: current
created: 2026-10-14
updated: 2026-10-14
tags: [get-brolls, ai-generation, storyboard, ui, pipeline, donor-research]
---

# AI generation: donor interfaces and production workflows

This source-based assessment expands the earlier generation-client and media-QC review. It is research for the proposed AI module, not an accepted implementation specification or a claim of provider access. The selected initial routes are GPT and Grok subscriptions and OpenRouter API; future providers should be addable. The editorial choice between a mandatory still-first sequence and optional direct video remains open.

## Evidence and inspected revisions

| Repository | Inspected commit | Focus |
|---|---|---|
| MoneyPrinterTurbo | `bbe7eb9ae3e7a44f4553070b82d4a126aad62a33` | WebUI, queued task snapshots, quoting, local editable projects |
| super-video-maker-skill | `3fec4aa66a1d4f8b249746eabc372547f67bba5c` | Recipes, reference/keyframe contracts, variant reuse, repair and QC |
| video-production-skills | `e19f1f300eddbb4f73764e66849792ece94ff0b7` | Motion briefs, asset/runtime/delivery distinctions, frame comparison |

The comparison baseline is get-brolls `01f1a627508a53015bc2036e2cf98f8e16a21d98`, including the [bounded Remotion acceptance](https://github.com/kovr33k/get-brolls/blob/01f1a627508a53015bc2036e2cf98f8e16a21d98/docs/GRAPHICS-PILOT-ACCEPTANCE.md). Research used first-party source and documentation. Donor skills were inspected as data, not activated. No donor application was installed or launched; no paid generation or editorial-quality benchmark was conducted.

## What UI actually exists

| Donor | Existing interface | Integration boundary |
|---|---|---|
| MoneyPrinterTurbo | Streamlit generation form; task/history tabs; result playback and parameter restoration | Its separate editable-project CLI is not integrated into this WebUI |
| Bomx | CLI-generated plans, JSON receipts, contact sheets and checklists | A browser review dashboard is listed as a roadmap item |
| Pluviobyte | Agent instructions and command-line QA artifacts | The inspected tree does not provide a comparable production/review application |

Sources: [MoneyPrinterTurbo UI](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/webui/Main.py#L1367-L1426), [editable-project boundary](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/docs/video-projects.md#L1-L12), [Bomx roadmap](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/README.md#L425-L430), [Pluviobyte tree](https://github.com/Pluviobyte/video-production-skills/tree/e19f1f300eddbb4f73764e66849792ece94ff0b7).

Task success is a production state, not human editorial approval. Preserve that distinction in our interface.

## Additional findings from MoneyPrinterTurbo

### Capability-sensitive controls and a request-bound estimate

The UI retains an unavailable selected model instead of silently substituting one. A charge estimate is bound to account and generation inputs; changing them clears confirmation. Failed quote requests pause until input changes or explicit retry. This mechanism is specific to its LoomLoom route. [Source](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/webui/Main.py#L4401-L4605).

**Application:** present only supported controls for the exact model/access route, retain invalid selections visibly, and bind a spending authorization to the prepared request. OpenRouter estimates and subscription usage require their own mechanisms; an unknown estimate must not be shown as zero.

### Narration coverage and visible shortfalls

Coverage uses an unchanged full-voice preview when available, otherwise an explicitly estimated duration range. It recommends clip count and displays shortfalls; a one-time recommendation does not repeatedly overwrite manual choices. [Source](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/webui/Main.py#L4304-L4334).

**Application:** show the target narration interval, available media duration and missing handles for each fragment. Do not import the donor's generic looping policy: a shorter AI output must retain an explicit shortfall rather than silently repeat to fill narration.

### Durable presentation of background work

The submission helper copies mutable parameters and preview inputs before queueing, records task state before scheduling, and turns a scheduling failure into a queryable state. This keeps later UI edits from mutating the job already submitted. [Source](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/app/services/webui_task.py#L133-L200).

**Application:** a collapsible job drawer in Storyboard can show waiting, submitted, downloading, technical failure and unresolved submission states. Keep the frozen input variant and provider operation visible. Opening review or saving a comment must not start production; generation remains within the explicitly authorized managing workflow.

### Explain exactly what a revision will rebuild

The separate local project module constructs audio, timing, scene, assembly and export dependencies. Its plan distinguishes verified reuse from changed dependencies, damaged artifacts and missing completed results. Scene-order changes affect assembly/export; BGM changes affect final export. Revisions retain prepared local media snapshots and toolchain fingerprints. This is implemented local rendering, not an AI-generation or WebUI executor. [Stage graph](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/app/services/video_project.py#L171-L240), [plan and integrity](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/app/services/video_project.py#L400-L479).

**Application:** surface a small `keep / rebuild / reason` plan for a requested AI revision. Our existing fingerprint-based continuation is the foundation; a second cache or timeline engine is unnecessary. The donor's assembled, narration-embedded output differs from our approved clips with separate VO and manual Resolve placement.

## Additional findings from Bomx

### Recipe manifests make a production request inspectable

Recipe data declares inputs, tools, expected artifacts, delivery settings, stages and paid-generation flags. The plan command lists paid stages. This is useful as a concise task contract, but its stages contain prose and its orchestrator mainly records stage notes; it does not enforce a full dependency-aware production workflow. [Recipe schema](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/recipes/schema.json#L52-L90), [dry-run plan](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/video_recipes.py#L357-L386), [orchestrator](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/video_orchestrator.py#L28-L66).

**Application:** extend our assignment with an AI operation mode and required inputs, not a generic recipe router or another application.

### First frame, last frame and style reference are different roles

The fal client implements distinct text, image and reference payloads. Image mode maps two images to a first and last frame; reference mode sends reference arrays. The tabletop playbook describes editing successive states of one base image and animating adjacent pairs. [Payloads](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/fal_seedance_video.py#L212-L253), [successive edited states](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/TABLETOP_EXPLAINER_PLAYBOOK.md#L50-L60).

**Application:** explicit slots for object/identity, style, first frame, last frame and motion reference. Show before/after states together. Enable a role only when the selected model and route support it; fal support does not establish the capabilities of GPT/Grok subscriptions or OpenRouter.

### A shared reference package and variants of one fragment

The UGC runner creates a character card and related image references, reuses them across variants, and shares a common body across alternative hooks. This is a concrete artifact-reuse example. The donor explicitly says `visual_seed` is a batch label rather than a reliable identity-control mechanism. [Reference preparation](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ugc_ad_runner.py#L214-L280), [shared variant body](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ugc_ad_runner.py#L558-L578), [seed limitation](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/SKILL.md#L218-L231).

**Application:** a versioned reference package for recurring objects or visual style and several takes under one scenario fragment. Selection is distinct from approval; approval binds to the exact files. A shared-reference change should list affected fragments while retaining earlier versions.

The donor runner can reuse a file based only on existence and size. Our richer input/runtime fingerprints should be retained. Generic fallback may switch paid providers or substitute an old hook, which can change cost and editorial meaning. [Reuse condition](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ugc_ad_runner.py#L419-L428), [fallback branches](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ugc_ad_runner.py#L383-L406).

### Review evidence should help choose the repair

The quality tool uses shot-plan risk terms to extract denser review windows and produce contact sheets and a manual checklist. This aids inspection; it does not automatically judge correct faces, actions or factual meaning. Guidance recommends crop/reframe, then image/layout edit, then regeneration, then replacement. [Targeted review](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ad_quality_gate.py#L477-L507), [review checklist](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/tools/ad_quality_gate.py#L593-L626), [repair ordering](https://github.com/Bomx/super-video-maker-skill/blob/3fec4aa66a1d4f8b249746eabc372547f67bba5c/SKILL.md#L112-L113).

**Application:** add a repair intent and affected timestamps to our existing revision request. A framing problem need not consume another model generation. Sensitive transition windows may need more frames than a generic three-frame contact sheet.

## Additional findings from Pluviobyte

The motion brief names the main object, start/end states, narrative purpose, action, camera/layer motion, text role and asset needs. These are useful assignment fields. The skill is instructional; its percentage-of-moving-beats rule is a creative rubric, not a universal documentary requirement or benchmark. [Beat contract](https://github.com/Pluviobyte/video-production-skills/blob/e19f1f300eddbb4f73764e66849792ece94ff0b7/ai-motion-director/SKILL.md#L77-L112).

Its alignment workflow separates source assets, actual timeline playback and decoded delivery. That distinction matters when an AI asset is later placed in Remotion: obtaining a correct file does not prove the correct file appeared in the final composition. Frame comparison applies to fixed source/export regressions, not quality ranking of independent stochastic generations. [Evidence layers and repair](https://github.com/Pluviobyte/video-production-skills/blob/e19f1f300eddbb4f73764e66849792ece94ff0b7/reference-video-replica-qc/references/alignment-workflow.md#L28-L100).

## Existing strengths to preserve

- One project and Storyboard with original scenario context, retained versions, exact-version review and explicit human decisions. [Review panel](https://github.com/kovr33k/get-brolls/blob/01f1a627508a53015bc2036e2cf98f8e16a21d98/scripts/getbrolls/graphics.py#L6782-L6806).
- Dependency-aware continuation, integrity checking and selective invalidation. [Continuation](https://github.com/kovr33k/get-brolls/blob/01f1a627508a53015bc2036e2cf98f8e16a21d98/scripts/getbrolls/graphics_continuation.py#L247-L273).
- Durable external-operation states and refusal to repeat an unknown submission. [Narration state contract](https://github.com/kovr33k/get-brolls/blob/01f1a627508a53015bc2036e2cf98f8e16a21d98/scripts/getbrolls/narration.py#L79-L106).
- Original and derived-media identity, actual dimensions and clocks, separate material-use permissions and human approval. [Media record](https://github.com/kovr33k/get-brolls/blob/01f1a627508a53015bc2036e2cf98f8e16a21d98/scripts/getbrolls/graphics_media.py#L120-L154).

## Recommended UI and pipeline scope

These are proposals, not new approvals or implemented behavior:

1. Keep one fragment in focus. Add stage-specific image, motion, review and delivery views to existing Storyboard; keep technical details and job history collapsed.
2. Show role-labeled references, input versions and before/after keyframes. Keep a selected take separate from an approved take.
3. Prepare a frozen generation request from scenario purpose, duration, references, motion brief and explicit provider/model/access route. Expose supported options rather than universal flags.
4. Display estimate/usage availability honestly. Preserve request-bound authorization and existing chat-activated production; a fresh visual variant is not automatically approved for paid animation.
5. Save operation and original result before local conform/review. Distinguish unknown submission, pending provider work, result-download failure and invalid media.
6. Offer crop, image edit, motion regeneration and replacement as different repair intents. Display the reuse/rebuild plan before processing an affected request.
7. Keep technical validity, editorial approval, material-use conditions and delivery readiness separate. A generated asset remains explicitly generated.

The small accompanying interface demonstration explores the still-first path only. Its states, references and controls are illustrative; they do not connect to providers or register real approvals. Checked interactions include variant-specific selection, loss of video readiness for a changed unapproved input, repair-plan updates and download-only recovery of a frozen example job. At a 375-pixel browser viewport, its 328-pixel content area had no horizontal overflow. This is QA of the demonstration, not acceptance of an AI module or donor WebUI.

## Reuse terms and evidence limits

MoneyPrinterTurbo has an [MIT license](https://github.com/harry0703/MoneyPrinterTurbo/blob/bbe7eb9ae3e7a44f4553070b82d4a126aad62a33/LICENSE). No license file was found in the complete inspected Bomx and Pluviobyte trees. Treat their work as reference ideas until reuse terms are established. No donor code has been added to the product.

The inspection does not prove OAuth media access, OpenRouter model entitlement, actual billing, generation quality, a savings percentage or Resolve acceptance. Those require bounded tests of the selected routes and actual outputs. Existing Remotion acceptance must not be reinterpreted as acceptance of generated media.
