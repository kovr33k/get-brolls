---
type: specification
status: accepted
created: 2026-10-15
updated: 2026-10-16
tags: [get-brolls, ai-generation, storyboard, design, interview]
---

# AI image and video production

This document records the design interview for the AI production module. The editor confirmed the consolidated workflow and first-version scope on 2026-10-16. Product/design acceptance does not establish implementation, provider access or real-media acceptance.

The consolidated [first-version contract](SPEC-AI-GENERATION.md) was accepted with this interview on 2026-10-16. It combines the confirmed decisions, shared-workflow integration and acceptance checks. Implementation proceeds under repository workflows; live operations retain their concrete authorization requirements.

## Confirmed starting scope

- Produce AI images and videos for scenario fragments.
- Support both API access and subscription/OAuth access.
- The initial subscription routes are GPT and Grok; the initial API route is OpenRouter.
- Allow additional providers to be added later.

These are product requirements, not proof that each requested generation operation is available through every selected access route.

## Existing product context

Use **AI-generated asset** as defined in [CONTEXT.md](../CONTEXT.md). The existing [motion-graphics design](DESIGN-MOTION-GRAPHICS.md) places later generated assets in the shared project workflow, as scene inputs or separately reviewed clips. The [donor assessment](research/AI-GENERATION-UI-PIPELINES.md) is research, not an accepted feature list.

The existing [saved graphics-reference workflow](GUIDE.md#saved-image-references) uses attachments plus editorial instructions and chat-activated processing. The AI module instead uses prompt-based revisions and direct Storyboard launch for follow-up work, as accepted in Q6 and Q8. Q14 accepts scene instructions with optional files, and Q16 includes both image and video references in the first version. The earlier demonstration UI is not an approval of its illustrated features or layout.

## Beat-level workflow

Confirmed by the editor on 2026-10-16: the agent first analyzes the original scenario, divides it into meaningful narrative beats and proposes which work belongs to source-based B-roll, Remotion graphics or AI production. Use **Narrative beat** as defined in [CONTEXT.md](../CONTEXT.md). The AI module receives the beats routed to it rather than independently replacing the shared scenario analysis.

For **each AI beat**, present three distinct scene alternatives. In the Storyboard the editor selects one alternative for that beat and may add a comment to the selected scene before production proceeds. The alternatives are choices for that beat, not three consecutive shots or three choices for the entire project. A selection or comment for one beat must remain associated with that beat and alternative.

Start in **AI economy mode**: present three textual scene alternatives, then generate the image for the editor's chosen alternative and comment. The editor can switch to **AI image comparison mode**, which prepares three images for visual selection. Use these terms as defined in [CONTEXT.md](../CONTEXT.md). Economy mode is the initial default; image comparison is available as an alternative, not a required first step.

After selection and image generation, follow the accepted still-first production and review checkpoints. A later prompt may request adjustments or an entirely different scene, with or without attached files. Launch follow-up work in the Storyboard and update status/results there. The representation mode does not change the agreed output quality, subscription-first policy or paid-launch confirmation requirements.

## Design interview

### Q1: Editorial role and entry into AI production

Decision: **A — accepted on 2026-10-15.** The managing agent may propose AI production as an independent visual approach when it best serves a scenario fragment, including an explanation, metaphor or illustration.

An unsuccessful source search is not a prerequisite for proposing AI. Generated material retains its explicit identity and is distinct from documentary evidence. This decision does not yet define generation authorization, spending limits or human review checkpoints.

### Q2: Default path from concept to AI video

Decision: **A — accepted on 2026-10-15.** The main production path is generated image, explicit human approval of that exact image, then video generated from it.

Use **AI still approval** as defined in [CONTEXT.md](../CONTEXT.md). This checkpoint settles the visual input before animation. It does not approve the resulting video or settle generation budgets and provider selection. Additional production modes have not been accepted by this decision.

### Q3: Concept selection before the first image generation

Initial decision: **A — accepted on 2026-10-15.** The managing agent selects AI fragments and visual concepts and prepares generated still drafts directly within the agreed visual style and spending/usage limits, without a routine separate textual concept-plan approval.

Revision on 2026-10-16: Q14/Q15 supersede the earlier initial drafting path. By default the editor first chooses one of three textual scene alternatives, then the agent generates the chosen image. In the optional image comparison mode, the alternatives are already generated stills. Q2 still requires approval of the exact image before video production.

### Q4: Initial image variants per fragment

Initial decision: **A — accepted on 2026-10-15.** Start with one image draft for each AI fragment, then edit it or generate an alternative when needed.

Revision on 2026-10-16: Q14/Q15 define three textual alternatives followed by one chosen image generation in the default economy mode. The optional image comparison mode prepares three generated images. All generation remains subject to the accepted authorization and correction limits.

### Q5: Visual style scope

Decision: **A — accepted on 2026-10-15.** Agree a common visual style for the project. The managing agent proposes it; the editor corrects it and may supply references.

Use **AI visual style** as defined in [CONTEXT.md](../CONTEXT.md). Scene-specific details can vary within the agreed direction. This does not require a separate style approval for every fragment or establish the reference intake and revision workflow.

### Q6: Revising an image that is close to the desired result

Decision: **Clarified by the editor on 2026-10-15.** The editor writes what is unsatisfactory or should change in a natural-language prompt for the selected image. A separate routine choice between editing and regeneration is unnecessary.

Use **AI image revision request** as defined in [CONTEXT.md](../CONTEXT.md). The module handles the technical method of applying the requested change and presents the result for review. Keep the earlier result and the target of the request identifiable. Q14 additionally accepts a prompt requesting a different scene, with optional reference files. Neither kind of request authorizes an unconfirmed paid launch or approves the resulting image for animation.

Interview adjustment: reserve further questions for meaningful editorial, workflow and cost decisions. Do not ask the editor to choose routine implementation mechanisms that can follow their prompt and the agreed product constraints.

### Q7: Default use of subscription routes and paid API access

Decision: **A — accepted on 2026-10-15.** Prefer suitable GPT/Grok subscription routes. Use the OpenRouter API only when the editor has explicitly authorized API use.

An unavailable operation or exhausted subscription quota does not authorize an automatic switch to paid API use. Q13 requires confirmation for each paid launch. Provider capabilities and generation quality must be established separately; this preference is not evidence that every requested operation is supported through a subscription route.

### Q8: Storyboard and generation launch

Decision: **B — accepted on 2026-10-15.** Launch follow-up work directly from the Storyboard where the editor reviews the result. An explicit Apply action submits the revision prompt for the selected image; a video-generation action starts work from an explicitly approved still. These actions do not require a subsequent instruction in chat.

The editor's stated concern is avoiding an extra trip to chat and manual Storyboard reloads. Show operation status and new results automatically without requiring a manual page reload. Refreshing the view must preserve the editor's selected fragment and unsent work. Automatic updates and the choice of launch surface are separate technical concerns; either launch surface could support automatic updates.

The Q2 exact-still approval and Q7 API-authorization rules still apply to Storyboard actions. A prompt being typed or an image being selected does not launch work. This decision covers follow-up interaction; it does not independently define new controls for the initial project setup or initial batch planned under Q3. This is an AI-module design requirement, not a claim that the current Storyboard already runs provider jobs.

### Q9: Generated-video coverage of a narration fragment

Decision: **A — accepted on 2026-10-15.** Produce visual coverage for the intended narration interval, using several clips when needed. The editor receives coverage tied to the scenario fragment rather than having to assemble unrelated short model outputs to fill that interval manually.

Use **AI sequence** as defined in [CONTEXT.md](../CONTEXT.md). Keep the original narration interval and the ordered clips identifiable. Q2 approval of each image used for video production remains in force; initial alternative selection follows the revised Q14/Q15 workflow. This coverage requirement does not authorize an unbounded number of additional generations. Q11 defines work before recorded narration; the exact shot-planning policy remains to be specified.

### Q10: Sound in generated clips

Decision: **A — accepted on 2026-10-15.** Include suitable atmosphere and sound effects when they serve the scene. Music and speech require a separate explicit request. Keep the project's narration separate from the delivered clip audio.

The selected provider's audio output still needs review; a successful generation does not establish that its sound is suitable. Sound generation/acquisition and mixing mechanisms are implementation details within this audio policy. An explicit request for music or speech does not establish support through every provider or access route.

### Q11: Work before recorded narration is available

Decision: **A — accepted on 2026-10-16.** Before narration is recorded, generate and approve images. Generate video after the recording is available, using its actual narration intervals.

The accepted workflow does not include generating estimated-duration video drafts before recorded narration. Existing approved images remain available as inputs for later video production. This decision concerns AI production and does not change the graphics module's separate draft-timing policy.

### Q12: Automatic correction of obvious generation defects

Decision: **A — accepted on 2026-10-16.** If the agent observes an obvious generation defect, it may spend one additional generation on correcting it within the authorized provider route and usage/spending limits. Present the resulting work to the editor afterward.

The allowance is at most one corrective generation per editor-requested generation operation; the correction does not start another automatic correction allowance. Retain the results and attempt history. This does not replace the required human approvals or authorize silently changing an approved image used for video. Q13 adds a confirmation requirement for every paid API launch, including this corrective generation; the agent must request that confirmation before proceeding through API. This decision concerns content defects, not retrying a failed download or reissuing a request with an unknown provider outcome.

### Q13: Scope of explicit OpenRouter API authorization

Decision: **B — accepted on 2026-10-16.** Request explicit confirmation in the Storyboard before each paid OpenRouter API generation launch. Project-level blanket API permission was not selected.

The confirmation applies to the planned launch, not later paid generations. A Q12 corrective generation through API also requires confirmation. The Q7 subscription-first policy remains the default; exhaustion or lack of a suitable subscription operation does not bypass confirmation. Present the confirmation where the work is launched rather than requiring an extra trip to chat.

### Q14: Three scene alternatives and prompt-led changes

Decision: **Clarified by the editor on 2026-10-16.** Initially the agent offers three scene alternatives; the editor chooses one of the three for generation. Use **AI scene alternative** as defined in [CONTEXT.md](../CONTEXT.md). These are alternative treatments of the same fragment, not three consecutive shots that must all be produced.

Further clarification on 2026-10-16: apply this to every beat routed to the AI module after the shared scenario breakdown and routing to B-roll, Remotion or AI. The editor clicks an alternative for each desired beat and can add a comment to that selected scene. See [Beat-level workflow](#beat-level-workflow).

For a correction, adjustment or a different scene, the editor writes a prompt describing the desired scene/change and requests generation again. Files are optional: the same workflow accepts a prompt with attachments or a prompt without attachments. Keep these actions in the Storyboard under Q8, with earlier results retained for comparison.

This revises the initial-selection assumptions in Q3/Q4. Q15 settles the two representation modes and their default; Q16 subsequently accepts image and video reference support.

### Q15: Representation of the three initial scene alternatives

Decision: **Two modes, economy by default — accepted on 2026-10-16.** The editor requested the proposed two-mode design with the default reversed: initially show three textual scene alternatives, with the option to switch to three generated images.

In **AI economy mode**, the editor selects one of three descriptions and may add a comment; generate the chosen image rather than generating images for every description. In **AI image comparison mode**, prepare three actual images, let the editor choose one and optionally request changes. Selecting a description does not approve an image that has not yet been generated, and a revised image still needs the Q2 approval before animation.

The [Business subscription image-limit check](research/GPT-IMAGE-SUBSCRIPTION-LIMITS.md) found no guaranteed image count in the official pages checked. Three images for each of N AI beats mean 3N initial images before revisions; this is not a subscription-capacity estimate or a fixed number of API requests. Both modes retain Q13 confirmation before each paid API launch.

### Q16: Reference media in the first version

Decision: **A — accepted on 2026-10-16.** Scene prompts and revisions can include both image and video references in the first version. The editor describes their intended use in the prompt. Use **AI reference** as defined in [CONTEXT.md](../CONTEXT.md).

This concerns reference inspection and applying the requested characteristics; it does not assume that every provider directly accepts video or add an independent video-to-video production mode. Files remain optional under Q14.

## Shared-understanding confirmation

The explicit product questions Q1-Q16 are recorded, including the Q3/Q4 revisions. The editor confirmed the consolidated workflow and first-version scope on 2026-10-16. The [first-version contract](SPEC-AI-GENERATION.md) gives a complete example, shared project/Resolve integration and verification boundaries. The [provider-route audit](research/AI-SUBSCRIPTION-ROUTES.md) establishes documentation/source evidence separately from actual media access.

The interview's shared-understanding checkpoint is complete. Implementation preparation can proceed. Concrete account, model, media-quality and Resolve acceptance remain future checks; API and pilot operations still require the accepted concrete authorization rather than treating design acceptance as a blanket paid-generation grant.

## Decision records and glossary

Resolved domain terms belong in CONTEXT.md. Product choices are recorded here as the interview proceeds. Create a separate ADR only for a meaningful, hard-to-reverse trade-off whose reason would otherwise be surprising. Do not infer approval from an illustrative UI selection, a donor feature, a successful provider response or an automated test.
