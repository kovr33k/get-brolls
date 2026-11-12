<div align="center">
  <p><a href="README.md">Português</a> · <strong>English</strong></p>
  <h1>SceneQuarry</h1>
  <p><strong>From script to material for your edit.</strong></p>
  <p>Source discovery, previews and scene review in a local project.</p>
  <p><img src="https://img.shields.io/badge/version-0.1.0-blue?style=flat-square" alt="Version 0.1.0"></p>
</div>

SceneQuarry is an independent project maintained by [kovr33k](https://github.com/kovr33k). It organizes footage and image discovery, Storyboard review and delivery with recorded provenance. It also includes the Remotion graphics and AI scene workflows documented in the [guide](docs/GUIDE.md); each route depends on the configured tools and accounts.

Supply a script or describe one scene. The agent finds literal sources, prepares previews and presents options for your decision. Stock is used when requested. Final delivery requires human approval and recorded use conditions; changes to the context or source interval require fresh review.

Supports local installations on **macOS and Windows**, through Codex or Claude Code. The code derives from an MIT project; see [origin and attribution](ATTRIBUTION.md). SceneQuarry has its own name, maintenance and version sequence, starting at 0.1.0. Inherited engineering history is not a release history for this brand.

## How it works


### What it collects



## Getting started

### 0. Install the whole stack

The skill only works end to end with **all** of the tools below installed before step 2. Missing one, the collection runs partially and the Storyboard comes out without a preview or without a numbered contact sheet.

| Tool | Used for | Without it |
|---|---|---|
| Python 3.11+ | CLI, ledger, Instagram collector | nothing runs |
| FFmpeg + ffprobe **with libfreetype** (`drawtext`) | poster, numbered contact sheet, GIF, cuts | no preview; without `drawtext` the sheet has no cell number/timecode and the Storyboard shows only the legend |
| Node 22+ with npm/npx | Playwright CLI and yt-dlp EJS runtime | YouTube and Instagram fail |
| curl | Instagram stream pair download | Instagram fails |
| Git | clone and update | manual installation |
| yt-dlp and Playwright CLI | installed by `install.sh`/`install.ps1` in step 2 | YouTube/TikTok and Instagram fail |

macOS (Homebrew):

```sh
brew install python ffmpeg node git curl
```

Windows (winget; Windows PowerShell 5.1 is enough):

```powershell
winget install Python.Python.3.13 Gyan.FFmpeg OpenJS.NodeJS.LTS Git.Git
```

Ubuntu/Debian:

```sh
sudo apt install python3 python3-venv ffmpeg nodejs npm curl git
```

After step 2, `python3 scripts/gb.py doctor` is the gate: empty `summary.missing` and `contact_sheet.labels: true`. If `drawtext` shows up under `summary.optional`, your FFmpeg was built without libfreetype: reinstall it with the command above (on macOS, `brew reinstall ffmpeg`).

### 1. Add the skill to your agent

The official repository is [kovr33k/scenequarry](https://github.com/kovr33k/scenequarry). Clone the source and copy the complete `scenequarry/` folder to **one** of the destinations below:

```sh
git clone https://github.com/kovr33k/scenequarry.git
cd scenequarry
```

| Agent | Personal installation | Inside a project | Invoke with |
|---|---|---|---|
| Codex | `~/.agents/skills/scenequarry/` | `.agents/skills/scenequarry/` | `$scenequarry` |
| Claude Code | `~/.claude/skills/scenequarry/` | `.claude/skills/scenequarry/` | `/scenequarry` |

When copying a development folder, exclude `.venv/`, `.tools/`, caches, projects, and private files. `skills/` and `.claude-plugin/` are Claude Code plugin artifacts and can be omitted when copying to Codex. Install dependencies in the final destination and open a new agent session. [See installation, updates, and compatibility.](docs/GUIDE.md#instalação)

#### Install as a Claude Code plugin

In Claude Code, you can also install the skill as a plugin, without cloning manually:

```text
/plugin marketplace add kovr33k/scenequarry
/plugin install scenequarry@kovr33k
```

Then run `/scenequarry-setup` in the session: the command runs the installer inside the plugin folder — `~/.claude/plugins/cache/kovr33k/scenequarry/<version>/` — and reports the `doctor` verdict. You can also follow step 2 manually in that folder. Repeat the setup after each `/plugin update`. For Codex, the full-folder clone described above remains the way to install.

The skill triggers from the context of your request ("collect b-roll for this video"); the explicit form is `/scenequarry:scenequarry`, and setup is `/scenequarry-setup`. Do not confuse it with generic download skills: this one is the complete pipeline, with human review and a recorded license.

### 2. Prepare the environment

Requirements are the stack from step 0. The [installation guide](docs/GUIDE.md#instalação) covers both platforms in full.

Run the installer for your operating system from the installed skill folder.

macOS:

```sh
bash scripts/install.sh --check
bash scripts/install.sh
python3 scripts/gb.py doctor
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Check
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
python scripts/gb.py doctor
```

The installer creates local environments and obtains yt-dlp/EJS and Playwright CLI. `--check` only validates prerequisites (Python, FFmpeg/ffprobe, Node, curl, Git) and installs nothing; run it before the full installer to see what is missing. `doctor` checks tool availability once installed; access to each source depends on the URL and, when required, your browser session.

**YouTube works without an API key.** Pexels and Pixabay use their own optional keys, configured in the environment or in the skill's private `.env` file. Available settings are documented in [.env.example](.env.example).

### 3. Make your first request

In Codex:

```text
$scenequarry I need three inserts for a video about the Artemis launch.
Find real footage of the rocket and liftoff, using clips between 3 and 5 seconds.
Prepare the previews and a storyboard for me to review.
Use /path/to/my-video to store the project.
```

In Claude Code, replace the first invocation with `/scenequarry`. Replace the folder with the real path to your project, outside the skill installation. You may also provide a specific URL or a local file.

### First B-roll in 5 minutes

The shortest command-line sequence, using a keyless source (NASA). Replace `/path/to/my-video` with your project and `<ID>` with the identifier returned by the search — keep the quotes, because identifiers may contain spaces.

```sh
python3 scripts/gb.py search --provider nasa --query "Artemis launch" --limit 3 --intent literal --project /path/to/my-video
python3 scripts/gb.py preview --candidate "<ID>" --start 0 --end 4 --project /path/to/my-video
python3 scripts/gb.py review --project /path/to/my-video
python3 scripts/gb.py serve --background --project /path/to/my-video
```

Open [the local storyboard](http://localhost:8767/review.html) at the URL the command returned right away, decide on the shots, and export the JSON — opening it via `file://` can disable local saving, so export before closing the page.

```sh
python3 scripts/gb.py import-review --by "Your name" --project /path/to/my-video
python3 scripts/gb.py serve --stop --project /path/to/my-video
python3 scripts/gb.py permit --candidate "<ID>" --evidence "Real conditions of use for this source" --project /path/to/my-video
python3 scripts/gb.py fetch --candidate "<ID>" --project /path/to/my-video
python3 scripts/gb.py verify --project /path/to/my-video
```

At the end, `verify` answers `"count": 1` and the approved clip is in `/path/to/my-video/brolls/clips/`, with origin, creator, and decision recorded in `brolls/credits.md`. Replacing `nasa` with `commons` follows the same flow.

### Onboarding checklist — chat only

If you have never opened a terminal, this is the whole list. Every step is a conversation with the agent; none of them asks for a command.

1. **Install once.** Ask for `/scenequarry-setup`. It installs everything and answers in one line whether you are ready. Repeat after every `/plugin update`.
2. **Say what you need.** `/scenequarry I need supporting footage for my Reel about X` — and say which folder the project lives in.
3. **Answer the interview.** At most seven questions, one at a time. "Whatever you think" is a valid answer: the agent applies a default and shows you what it assumed. To start there directly, use `/scenequarry-brief`.
4. **Check the brief.** It hands back five lines of what it understood and asks whether that is right. Correct it there.
5. **Look at the shortlist.** Before downloading anything, it lists 5 to 8 candidates with title, creator, and the exact window. Say which ones work.
6. **Approve the previews.** Either in chat ("I approve all", or naming the ones you want), or on the Storyboard: ask for `/scenequarry-review`, it sends you a link, you click Approve / Request change / Reject and then **Save decisions**, and come back to say you saved. Nothing is downloaded without this step.
7. **Say who owns the material.** The agent records the usage conditions from what you tell it. You are the one answering for those conditions; it only records what was said and where each file came from.
8. **Receive.** The cuts land in `entrega/`, one folder per shot, each with an `ORIGEM.md` naming its source.
9. **Lost the thread?** Ask for `/scenequarry-status`: it tells you where things stand and what comes next.

## Commands

In order of use — from first contact to delivery:

**1. Install the environment** (once, in the plugin or clone folder):

```text
/scenequarry-setup   # installs dependencies and runs doctor
```

**2. Invoke the skill** with what you need:

```text
/scenequarry <your request>   # Claude Code — describe the inserts and the project folder
$scenequarry <your request>   # Codex — same thing
/scenequarry-brief            # interviews you and writes the video's BRIEF.md
/scenequarry-review           # builds the Storyboard, sends the link, imports the decisions
/scenequarry-status           # says where the collection stands and what comes next
```

**3. Check the environment** when something misbehaves:

```text
python3 scripts/gb.py doctor   # verifies tools and names what is missing
```

**4. Search and choose** (the agent runs these for you, but they work by hand):

```text
python3 scripts/gb.py search ...    # search candidates in the chosen source
python3 scripts/gb.py preview ...   # build GIF/contact sheet for the range
python3 scripts/gb.py review ...    # assemble the brolls/review.html storyboard
python3 scripts/gb.py serve ...     # serve the storyboard at http://localhost:8767/review.html
```

**4b. Paced social batches** (optional, for several Reels/videos at once):

```text
python3 scripts/gb.py queue --action add|next|mark|status ...   # enqueue, get the next item at the right pace, close it out
```

**5. Decide and receive**:

```text
python3 scripts/gb.py import-review ...   # import your storyboard decisions
python3 scripts/gb.py permit ...          # record the source usage conditions
python3 scripts/gb.py fetch ...           # download the approved final cut
python3 scripts/gb.py verify ...          # verify the delivery in the project
```

**6. Lost?** Ask where the project stands:

```text
python3 scripts/gb.py status --project /path/my-video   # per-stage summary, read-only
```

Every subcommand accepts `help`; full syntax lives in the terminal section.


## Highlights

- **Local storyboard.** `review` generates `brolls/review.html`: a page to switch between a still image and a GIF, see the narration, time range, selection rationale, creator, and source, and approve, request an adjustment, or suggest another source per shot. [Storyboard details.](#storyboard)
- **Integrated sources.** YouTube and TikTok without an API key via yt-dlp/FFmpeg, Instagram through the authorized browser with an included video/audio pair collector, Pexels and Pixabay with their own keys, Wikimedia Commons, NASA and Archive.org without a key, and local file import. [See sources and transports.](#sources)
- **Project state at any moment.** `status --project` summarizes candidates, previews, decisions, permissions, and deliveries, with the suggested next step, without changing the project. [See command-line usage.](#command-line-usage)
- **Paced social batches.** `queue` enqueues Instagram/TikTok/YouTube URLs and only returns the next item once the interval and hourly/daily caps allow it — the CLI never sleeps, it tells you how long to wait. `serve` runs the local Storyboard at `http://localhost:8767/review.html` without a loose `http.server` command.
- **Provenance record.** Every delivered shot carries source, creator, time range, and conditions of use — editorial approval is always yours.
- **Protected network access.** The collector accepts only public HTTPS URLs without credentials, rejects hostnames that resolve to local networks, and does not follow redirects.
- **Native on macOS and Windows.** Dedicated installers for both systems; the Bash YouTube helpers are optional.
- **Installable as a Claude Code plugin.** The repository itself is its own plugin marketplace, with `/scenequarry-setup` configuring the plugin folder and a mirrored skill that resolves paths via `${CLAUDE_PLUGIN_ROOT}`. The clone-as-skill flow remains identical for Codex.

## Storyboard

The `review` command generates `brolls/review.html`: a local page where you can evaluate the collection, move between shots, and send decisions back to the agent.

| In the review | What you can do |
|---|---|
| Selected shot | Switch between a still image and a GIF while preserving the original aspect ratio. |
| Context and origin | Inspect the supplied narration, time range, selection rationale, creator, and source link. |
| Decision per shot | Approve, Request a change (comment required; "find another video" lives inside it), or Reject. |
| Save decisions | Download a JSON file for the agent to import into the project. |
| Print / PDF | Generate a static version with frames, sources, and comments. |

The gallery remains static; animation runs only in the selected shot and respects reduced-motion preferences. An optional screenshot of the speaker provides context and remains static. To evaluate a finished composition using the same insert, set `GB_GIF_SCOPE=full` and provide `--full-preview-file`.

Share the complete **`brolls/` folder** so that its images and GIFs remain accessible. To continue editing or regenerate previews, also preserve the originals and `.getbrolls-sources/`. [Review details.](docs/GUIDE.md#storyboard)

## Sources

| Source | How to find it | How it is obtained |
|---|---|---|
| **YouTube** | Keyword search or URL | yt-dlp + FFmpeg; no API key. |
| **Instagram** | Reel found in the browser | Captures video and audio from the same Reel; the included collector joins both streams. |
| **TikTok** | Complete URL discovered in the browser | yt-dlp + FFmpeg; no API key. |
| **Pexels / Pixabay** | Search their stock APIs | Provider-specific key; HTTPS download. |
| **Wikimedia Commons / NASA** | Search public APIs | HTTPS download; no key. |
| **Archive.org** | Public search and explicit item/file resolution | Selected HTTPS file; resumable fragment plan; separate approval/rights gates. |
| **Local file** | Supplied video, image, or screenshot | Local import with origin and creator when provided. |

Pexels and Pixabay are an optional route: the agent turns to stock libraries only when you explicitly ask for stock. The default is the literal source of what the narration cites.

For Instagram, the agent operates the authorized browser and passes both streams to the collector; the script does not capture the session by itself. The [Instagram guide](docs/GUIDE.md#instagram--navegadorplaywright-dois-streams-e-mp4) covers stream pairing, download, audio, and recovery. Instagram and TikTok depend on URL discovery in the browser; the CLI does not implement global keyword search for those platforms.

The collector accepts only public HTTPS URLs without credentials, rejects hostnames that resolve to local networks, pins downloads to the validated address, and does not follow redirects. Files declared through `output=` must remain inside `--config-output-root`; batch outputs stay in the selected directory, and existing files are never overwritten.

Recorded trials include real acquisition from YouTube, Instagram, TikTok, Pexels, and Pixabay. For Commons and NASA, the evidence covers search and file availability without downloading the complete asset during that trial. See the results and their limitations in [Quality and evidence](docs/QUALITY.md).

## Command-line usage

Run the examples below from the skill folder. Replace `/path/to/my-video` with your project folder and `<ID>` with the identifier returned by the search — keep the quotes, because identifiers may contain spaces.

```sh
python3 scripts/gb.py status --project /path/to/my-video
python3 scripts/gb.py rules --project /path/to/my-video
python3 scripts/gb.py references --project /path/to/my-video
python3 scripts/gb.py search --provider youtube --query "NASA Artemis launch" --limit 3 --intent literal --project /path/to/my-video
python3 scripts/gb.py preview --candidate "<ID>" --start 0 --end 5 --reason "Show the liftoff mentioned in the video" --project /path/to/my-video
python3 scripts/gb.py review --project /path/to/my-video
python3 scripts/gb.py serve --background --project /path/to/my-video
```

Open [the local storyboard](http://localhost:8767/review.html) at the URL the command returned right away, review the shots, and export your decisions — opening it via `file://` can disable local saving, so export before closing the page.

```sh
python3 scripts/gb.py import-review --by "Reviewer's name" --project /path/to/my-video
python3 scripts/gb.py serve --stop --project /path/to/my-video
python3 scripts/gb.py permit --candidate "<ID>" --evidence "Real evidence of the conditions of use" --project /path/to/my-video
python3 scripts/gb.py fetch --candidate "<ID>" --project /path/to/my-video
python3 scripts/gb.py verify --project /path/to/my-video
```

Replace the name and evidence with real data. Repeat `permit` and `fetch` for every approved candidate. `approve` can also record an explicit decision you have already received. `verify` checks file integrity and decoding; the editorial judgment remains yours.

`status` answers where the collection stands at any moment — candidates, previews, decisions, permissions, and deliveries, with the suggested next step — and never changes the project. Flow commands also return a `summary` field with a one-line account of what just happened. [Project state and progress.](docs/GUIDE.md#estado-do-projeto-e-progresso)

<details>
<summary>URLs, local files, and settings</summary>

- Specific URL: `resolve --url REAL_URL --shot insert-01 --project /path/to/my-video`.
- Local file: `resolve --file /path/to/original.mp4 --source-url REAL_URL --creator "Creator" --shot insert-01 --project /path/to/my-video`. Use real metadata; a source without a URL may omit `--source-url`.
- Exact narration: add `--narration` to the preview when a script has been supplied.
- Project rules: `init-rules --project /path/to/my-video` creates an editable [RULES.md](docs/RULES.md) with formats, preferred sources, and blocks.
- Choice memory: `remember` records approved or rejected references; `references` reads the history for that project.
- Images and news: import the file or screenshot with its provenance. See [media types](docs/GUIDE.md#tipos-de-assets-e-formatos) and [browser captures](docs/GUIDE.md#captura-de-notícias-e-páginas-pelo-navegador).
- Default GIF: 360 px, 8 fps, 128 colors, up to 10 seconds and 5 MB. A time range beyond the duration limit is rejected; an oversized result falls back to a still preview with a warning. `GB_PREVIEW_MODE=static` uses a poster and contact sheet.
- `--reference-only` prepares a static reference without obtaining remote media; a poster alone does not prove motion.
- The utilities in `scripts/getbrolls/tools/youtube/` provide YouTube search, frames, clips, and verification by `VIDEO_ID`. Their output must be imported through the CLI to become part of the project's record and review.

Use `python3 scripts/gb.py --help` and `python3 scripts/gb.py preview --help` to inspect arguments. Outside the skill folder, use the absolute path to `scripts/gb.py`.

</details>

When upgrading to 2.3.5, regenerate the Storyboard and export a current review. JSON files based on superseded decisions or missing `reviewEpoch` are rejected. [Migration guide (Portuguese).](docs/GUIDE.md#migração-para-235)

## Limits and privacy

Project files and imported originals remain local. Remote search and acquisition connect to the selected providers. Keep API keys, browser sessions, Instagram configs, and signed URLs in a private environment; that data does not belong in the distributed skill folder.

The storyboard is intended for trusted local projects and does not authenticate reviewers. Share only the material required for review. Conditions of use belong to each source; recording a decision does not automatically verify its license. Responsibility for the conditions of use of the material lies with whoever produces the video; the skill answers for source fidelity and for recording the provenance of every asset.

Final resolution depends on the source: prefer 1080p when available and inspect the actual dimensions. The tool preserves aspect ratio and reports format mismatches. It does not automatically assemble the complete video, perform image search through an API, or deliver isolated audio as a final asset.

Run one command per project at a time. Preserve originals, cache, and event history. If the record is saved but page generation fails, run `review` again. The CLI and installer are native on macOS and Windows; the Bash YouTube helpers are optional and have equivalents in the main CLI workflow. See [compatibility](docs/GUIDE.md#compatibilidade).

## Documentation

| Entry | Purpose |
|---|---|
| [README.md](README.md) | Product overview and first use in Portuguese. |
| **[README.en.md](README.en.md)** | Product overview and first use in English (this file). |
| [AGENTS.md](AGENTS.md) | Index for agents and maintainers: repository map, per-agent installation, and maintenance rules. |
| [docs/MANUAL.md](docs/MANUAL.md) | Manual + tutorial in Portuguese: every command explained, output format, BRIEF/RULES/.env, and automation. |
| [docs/GUIDE.md](docs/GUIDE.md) · [SKILL.md](SKILL.md) | Complete operating guide and agent execution instructions. |
| [docs/QUALITY.md](docs/QUALITY.md) | Tests, real-world evidence, and known limitations. |
| [docs/RULES.md](docs/RULES.md) · [.env.example](.env.example) | Editorial rules and configuration options. |
| [docs/SECURITY.md](docs/SECURITY.md) | Handling of private data and vulnerability reporting. |
| `scripts/getbrolls/` | Single core: CLI, providers, Storyboard, Instagram collector, and YouTube utilities. |
| `assets/` | Styles and scripts used by the generated Storyboard. |
| `agents/` · `schemas/` | Agent presentation and data contract. |
| `tests/` · `.github/workflows/` | Tests and quality automation. |

To maintain the project, start with [CONTRIBUTING](CONTRIBUTING.md) and [AGENTS](AGENTS.md). See [QUALITY](docs/QUALITY.md), [CHANGELOG](CHANGELOG.md), and [SECURITY](docs/SECURITY.md) for evidence, changes, and handling of private data. The cloned repository (or the plugin installation) is the official source of the deliverable.

## Maintenance and origin

Maintained independently by [kovr33k](https://github.com/kovr33k). The original code authorship and license are recorded in [ATTRIBUTION.md](ATTRIBUTION.md).

Code is available under the [MIT License](LICENSE). External dependencies retain their own terms, listed in [Third-party notices](THIRD_PARTY_NOTICES.md).
