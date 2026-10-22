---
type: research
status: current
created: 2026-10-16
updated: 2026-10-16
tags: [get-brolls, ai-generation, subscription, oauth, worker, feasibility]
---

# Subscription generation from a local Storyboard worker

This read-only audit checks whether the accepted direct Storyboard actions require another message in the desktop chat. It establishes documented and source-level routes, not working account access. No media generation, login, installation or credential/profile inspection was performed. Executable help/version checks reported Codex CLI 0.157.1 and Grok 1.0.52; presence is not media acceptance.

## Route boundaries

| Route | Evidence | Unverified boundary |
|---|---|---|
| Native Codex with ChatGPT CLI login, images and edits | Published source matching the installed CLI and official image/noninteractive documentation provide a native worker path | Account entitlement, actual returned media, artifact handoff and operational integration |
| Third-party Sign in with ChatGPT Responses access | Official preview excludes hosted image generation | This is not interchangeable with native Codex tools |
| GPT subscription video | No supported native Codex video route established | Do not advertise GPT video as an implemented first-version capability |
| Native Grok with xAI OAuth, images/edits/video | Official headless documentation and public tool implementations provide a credible route | Public main is not proven identical to the installed binary; entitlement and output remain untested |
| OpenRouter API, images/video | Dedicated official endpoints support worker submission and result retrieval | Every paid launch still needs the accepted Storyboard confirmation; account/model access remains untested |

## Native Codex image worker

Official documentation describes built-in image generation and saved-login reuse in noninteractive mode. The current image page names `gpt-image-2`; do not infer the latest API image model from subscription access. [Image generation](https://learn.chatgpt.com/docs/image-generation), [noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

The published `rust-v0.157.1` source, matching the checked CLI version, starts a native in-process app-server for `codex exec`, installs the image extension and registers its tool using provider authorization. This supplies a worker architecture with its own bounded turn rather than requiring an active desktop conversation. [Exec startup](https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/exec/src/lib.rs#L985-L990), [extension registration](https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/app-server/src/extensions.rs#L98-L103), [image tool](https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/ext/image-generation/src/extension.rs#L38-L110).

Artifact handoff needs a concrete integration check: this release's exec JSON mapper does not emit the native image-generation item, whereas the native app-server protocol exposes `savedPath`. A zero exit code or a text answer is insufficient; inspect the returned image bytes and preserve their identity. [Exec JSON mapper](https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/exec/src/event_processor_with_jsonl_output.rs#L130-L324), [image item](https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/app-server-protocol/schema/typescript/ImageGenerationItem.ts).

The separate public SIWC route excludes hosted image generation. Its limitation must not be used either to promise images through arbitrary OAuth Responses access or to rule out native Codex generation. [SIWC limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Native Grok media worker

Inspected public source: `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`. Its equality to installed stable 1.0.52 was not established.

- Headless mode documents access to enabled tools. Media implementations include image generation/editing and image/reference-to-video, with saved image/video files. [Headless guide](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/docs/user-guide/14-headless-mode.md#L1-L15), [image generation](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/image_gen/mod.rs#L1-L16), [image editing](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/image_edit/mod.rs#L1-L10), [video](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/video_gen/mod.rs#L1-L59).
- Imagine side calls explicitly support OAuth bearer resolution, but the source also contains static-key fallback. A subscription-only integration must prevent that fallback and verify the intended route. [Bearer resolution](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-login/src/side_call_bearer.rs#L1-L74).
- The inspected image-to-video tool constrains duration/resolution differently from general marketing maxima. Discover and validate the actual installed tool/account limits rather than assuming native Full HD or arbitrary duration. An upgrade message is not generated media. [Video constraints](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/video_gen/mod.rs#L36-L59), [image access result](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/image_gen/mod.rs#L453-L496).
- Pager slash instructions alone do not prove headless expansion. Use a bounded media-tool request in the pilot. In particular, a generic multi-shot imagine instruction must not silently replace the exact approved still before animation. [Pager commands](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/slash_commands.rs#L432-L485), [headless resolution](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/slash_commands.rs#L1554-L1635).

## OpenRouter and acceptance

Official docs describe `POST /api/v1/images` and asynchronous `POST /api/v1/videos`, polling and authenticated content retrieval. Model and operation capabilities must be checked independently. [Image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation), [Video API](https://openrouter.ai/docs/guides/overview/multimodal/video-generation).

The bounded acceptance chain is exact request and input → intended auth route → actual returned media → saved project version → automatic Storyboard update → human review. Documentation, a tool registry, process success and an API job ID do not complete that chain. See the [implementation contract](../SPEC-AI-GENERATION.md) and the separate [subscription-capacity check](GPT-IMAGE-SUBSCRIPTION-LIMITS.md).
