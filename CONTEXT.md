---
type: reference
status: current
created: 2026-10-03
updated: 2026-10-10
tags: [get-brolls, catalogs, motion-graphics, domain-model]
---

# Get-brolls domain language

Domain terms used when designing searches, authored graphics and AI production for scenario fragments. Catalog-specific routes are described in [SOURCE-CATALOGS.md](docs/SOURCE-CATALOGS.md); user-facing wording is covered by [glossario.md](references/glossario.md).

## Language

**Narrative beat**:
A meaningful unit of original scenario text used to plan its visual treatment and route work to the relevant production module.
_Avoid_: Search query, fixed-duration clip, generated asset

**Search fragment**:
A portion selected directly from the original scenario as one visual search task. Its scope is chosen according to meaning.
_Avoid_: Query, subfragment

**Search query**:
A formulation submitted to a catalog to find material for a search fragment. Its language can differ from the scenario language.
_Avoid_: Scenario line, search fragment

**Search chain**:
An ordered list of catalogs selected for one search fragment.
_Avoid_: Global catalog order

**Search option**:
A distinct editorial choice of visual material for a search fragment. Different relevant scenes or moments from the same recording can be separate options.
_Avoid_: Catalog, repost

**Duplicate option**:
The same visual material represented by a repost, a near-identical trim, or a small shift in the boundaries of the same shot.
_Avoid_: Alternative scene

**Suitable option**:
A search option whose visible content has been inspected in the actual material or a preview and assessed as matching the search fragment.
_Avoid_: Promising search hit, human-approved option

**Search attempt**:
One meaningfully different search query and assessment of its returned results for a search fragment.
_Avoid_: Viewed video, preview frame, repeated identical query

**Search pass**:
Traversal of one planned search chain for a search fragment.
_Avoid_: Search query, catalog

## Motion graphics language

**Graphics scene**:
An authored visual composition for a scenario's visual purpose, combining text, shapes, data or supplied media over time.
_Avoid_: Search option, model-generated video

**Graphics template**:
A reusable design for a class of graphics scenes, with adaptable content, appearance and timing.
_Avoid_: Finished clip, custom graphics scene

**Custom graphics scene**:
A graphics scene authored for a particular visual purpose that an existing graphics template does not adequately express.
_Avoid_: Graphics template, search option

**Graphics overlay**:
An authored graphics element placed over real video or a photograph as part of a scene for a scenario's visual purpose.
_Avoid_: Standalone graphics scene, source footage

**Graphics assignment**:
A request to produce or revise one graphics scene, carrying its intended visual purpose and narrative context. A chapter can contain multiple graphics assignments.
_Avoid_: Search fragment, finished graphics scene

**Narration alignment**:
A correspondence between passages of the scenario and time intervals in recorded narration, used to place and time graphics scenes.
_Avoid_: Estimated scene duration, graphics animation

**Narration analysis**:
A saved Inworld transcription of a complete local recording, retaining original recognized text and word timestamps. Scene matching is a later, separate step.
_Avoid_: Scene match, estimated scene duration, graphics approval

**Graphics version**:
A saved iteration of one graphics scene, including its rendered video, authored composition and the data and source evidence used in it.
_Avoid_: New graphics scene, graphics template

**Graphics approval**:
A human editorial decision accepting a specific graphics version for its intended scenario use.
_Avoid_: Automatic approval, approval of all future scene versions

**Graphics revision request**:
A saved editorial request to change an identified graphics scene version, with a stated scope and desired change.
_Avoid_: Graphics approval, completed revision

**Graphics sound effect**:
A sound selected for a visual event in a graphics scene, with its timing and level belonging to that scene version.
_Avoid_: Voice-over, background music

## AI production language

**AI-generated asset**:
A model-generated image or video proposed as visual material for a scenario fragment.
_Avoid_: Documentary source, graphics scene

**AI still approval**:
A human editorial decision accepting a specific AI-generated image as the visual input for video production.
_Avoid_: Graphics approval, video approval, generation success

**AI visual style**:
The agreed project-wide appearance that guides AI-generated assets, including realism, palette and lighting.
_Avoid_: Individual image prompt, graphics template, provider preset

**AI image revision request**:
A natural-language request to change a selected AI-generated image, stating what is unsatisfactory or what should change.
_Avoid_: Image approval, completed edit, new unrelated concept

**AI sequence**:
An ordered set of one or more AI-generated clips intended to cover a scenario fragment's narration interval.
_Avoid_: Single provider response, complete chapter, narration recording

**AI scene alternative**:
A distinct visual treatment of a scenario fragment offered for editorial selection.
_Avoid_: Consecutive shot, approved video, saved revision

**AI economy mode**:
A scene-comparison mode that presents textual alternatives before generating the chosen image.
_Avoid_: Lower image quality, cheaper provider, API billing mode

**AI image comparison mode**:
A scene-comparison mode that presents alternatives as generated images for visual selection.
_Avoid_: Video approval, automatic animation, consecutive shots

**AI reference**:
An image or video supplied with editorial instructions to guide an AI scene's appearance, content or motion.
_Avoid_: Approved animation input, documentary evidence, automatic media inclusion

**AI generation job**:
A bounded request to produce a specified AI image or clip from identified scene inputs.
_Avoid_: Editorial approval, scene alternative, resumed download
