import {bundle} from "@remotion/bundler";
import {ensureBrowser, renderMedia, selectComposition} from "@remotion/renderer";
import fs from "node:fs";
import process from "node:process";

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index === process.argv.length - 1) {
    return null;
  }
  return process.argv[index + 1];
}

function refuseDownload() {
  throw new Error(
    "The local Remotion browser is not prepared. Run python scripts/gb.py graphics-doctor --prepare-browser. Render will not download a browser or a network font.",
  );
}

function frozenChoice(job, name, expected) {
  if (job[name] !== expected) {
    throw new Error(`Frozen graphics job must set ${name} to ${JSON.stringify(expected)}.`);
  }
  return expected;
}

const OWNED_CUE_SRC = /^audio\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
const OWNED_BG_SRC = /^media\/[A-Za-z0-9][A-Za-z0-9._-]*$/;

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertSafeCue(cue) {
  if (!isPlainObject(cue)) {
    throw new Error("Frozen graphics job sound cue is invalid.");
  }
  if (typeof cue.id !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(cue.id)) {
    throw new Error("Frozen graphics job sound cue needs a safe id.");
  }
  const src = cue.src;
  if (typeof src !== "string" || !OWNED_CUE_SRC.test(src)) {
    throw new Error("Frozen graphics job sound cue src must be a local audio/<file> path.");
  }
  if (src.includes("..") || src.includes("\\") || src.includes(":") || /^(?:https?:|file:|data:)/i.test(src)) {
    throw new Error("Frozen graphics job cannot include remote or extra-protocol audio sources.");
  }
  for (const key of ["start_frame", "trim_before_frame"]) {
    if (!Number.isInteger(cue[key]) || cue[key] < 0) {
      throw new Error(`Frozen graphics job sound cue ${key} must be a nonnegative integer.`);
    }
  }
  if (!Number.isInteger(cue.duration_in_frames) || cue.duration_in_frames < 1) {
    throw new Error("Frozen graphics job sound cue duration_in_frames must be a positive integer.");
  }
  if (typeof cue.gain !== "number" || !Number.isFinite(cue.gain)) {
    throw new Error("Frozen graphics job sound cue gain must be finite.");
  }
  if (cue.vo != null || cue.source_ref != null || cue.kind === "full_recording") {
    throw new Error("Frozen graphics job cannot include voice-over.");
  }
}

function assertSafeBackground(background) {
  if (background == null) {
    return;
  }
  if (!isPlainObject(background)) {
    throw new Error("Frozen graphics job background must be an object.");
  }
  if (background.kind !== "video" && background.kind !== "image") {
    throw new Error("Frozen graphics job background kind must be video or image.");
  }
  const src = background.src;
  if (typeof src !== "string" || !OWNED_BG_SRC.test(src)) {
    throw new Error("Frozen graphics job background src must be a local media/<file> path.");
  }
  if (src.includes("..") || src.includes("\\") || src.includes(":") || /^(?:https?:|file:|data:)/i.test(src)) {
    throw new Error("Frozen graphics job cannot include remote or extra-protocol background sources.");
  }
  if (src.includes("narration/private") || src.startsWith("/") || src.includes("://")) {
    throw new Error("Frozen graphics job cannot include private or remote background sources.");
  }
  if (background.fit !== "contain" && background.fit !== "cover") {
    throw new Error("Frozen graphics job background fit must be contain or cover.");
  }
  if (!Number.isInteger(background.trim_before) || background.trim_before < 0) {
    throw new Error("Frozen graphics job background trim_before must be a nonnegative integer.");
  }
  if (!Number.isInteger(background.duration_in_frames) || background.duration_in_frames < 1) {
    throw new Error("Frozen graphics job background duration_in_frames must be a positive integer.");
  }
  if (!Number.isInteger(background.width) || background.width < 1 || !Number.isInteger(background.height) || background.height < 1) {
    throw new Error("Frozen graphics job background width and height must be actual positive integers.");
  }
  if (background.muted !== true) {
    throw new Error("Frozen graphics job background source audio must stay muted.");
  }
  if (background.loop != null || background.playbackRate != null) {
    throw new Error("Frozen graphics job background cannot loop or be retimed beyond the confined bounds.");
  }
  if (background.vo != null || background.volume) {
    throw new Error("Frozen graphics job cannot include background audio or voice-over.");
  }
}

function assertSafeBackgroundProps(job) {
  if (job.background != null) {
    throw new Error("Frozen graphics job cannot carry a top-level background; use confined props.background.");
  }
  const props = isPlainObject(job.props) ? job.props : {};
  assertSafeBackground(props.background);
}

function assertNoVoiceOver(job) {
  const props = isPlainObject(job.props) ? job.props : {};
  if (job.props != null && !isPlainObject(job.props)) {
    throw new Error("Frozen graphics job props must be an object.");
  }
  if (
    props.vo != null ||
    props.vo_preview != null ||
    props.narration_audio != null ||
    job.vo != null ||
    job.vo_preview != null ||
    job.narration_audio != null
  ) {
    throw new Error("Frozen graphics job cannot include voice-over.");
  }
}

function audioSettings(job) {
  assertNoVoiceOver(job);
  const audio = job.audio;
  if (audio == null) {
    if (job.props && Array.isArray(job.props.sound_cues) && job.props.sound_cues.length) {
      throw new Error("Legacy silent graphics jobs cannot carry sound_cues.");
    }
    return {muted: true};
  }
  if (!isPlainObject(audio) || audio.mode !== "effects" || audio.codec !== "aac") {
    throw new Error('Frozen graphics job audio must be omitted (legacy silence) or {mode:"effects",codec:"aac"}.');
  }
  const extra = Object.keys(audio).filter((key) => key !== "mode" && key !== "codec");
  if (extra.length) {
    throw new Error("Frozen graphics job audio has unsupported keys: " + extra.join(", ") + ".");
  }
  const cues = job.props && job.props.sound_cues;
  if (!Array.isArray(cues) || !cues.length) {
    throw new Error("Effects audio mode requires local sound_cues.");
  }
  cues.forEach(assertSafeCue);
  return {muted: false, audioCodec: "aac"};
}

const prepareAllowed = process.env.GB_GRAPHICS_PREPARE_BROWSER === "1";

async function probeBrowser(browserExecutable = null) {
  return ensureBrowser({
    browserExecutable,
    onBrowserDownload: () => {
      refuseDownload();
    },
  });
}

if (process.argv.includes("--status-browser")) {
  try {
    const status = await probeBrowser();
    process.stdout.write(`${JSON.stringify(status)}\n`);
    process.exit(status.type === "no-browser" || status.type === "version-mismatch" ? 2 : 0);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({type: "no-browser", error: String(error.message || error)})}\n`);
    process.exit(2);
  }
}

if (process.argv.includes("--ensure-browser")) {
  if (!prepareAllowed) {
    refuseDownload();
  }
  const status = await ensureBrowser();
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exit(0);
}

const jobPath = arg("--job");
if (!jobPath) {
  throw new Error("Missing --job path.");
}

delete process.env.GB_GRAPHICS_PREPARE_BROWSER;

const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
const requested = job.browserExecutable || null;
if (requested && !fs.existsSync(requested)) {
  throw new Error(
    "Recorded Remotion browser executable is missing. Run python scripts/gb.py graphics-doctor --prepare-browser. Render will not download a browser.",
  );
}

const status = await probeBrowser(requested);
if (!status.path || status.type === "no-browser" || status.type === "version-mismatch") {
  refuseDownload();
}

const serveUrl = await bundle({
  entryPoint: job.entry,
  publicDir: job.publicDir,
});

const composition = await selectComposition({
  serveUrl,
  id: job.composition,
  inputProps: job.props,
  browserExecutable: status.path,
  onBrowserDownload: refuseDownload,
});

assertSafeBackgroundProps(job);
const audio = audioSettings(job);

await renderMedia({
  composition: {
    ...composition,
    width: job.width,
    height: job.height,
    fps: job.fps,
    durationInFrames: job.durationInFrames,
  },
  serveUrl,
  codec: frozenChoice(job, "codec", "h264"),
  outputLocation: job.output,
  inputProps: job.props,
  concurrency: job.concurrency || 1,
  crf: job.crf || 18,
  pixelFormat: frozenChoice(job, "pixelFormat", "yuv420p"),
  colorSpace: frozenChoice(job, "colorSpace", "bt709"),
  imageFormat: frozenChoice(job, "imageFormat", "png"),
  x264Preset: "medium",
  muted: audio.muted,
  ...(audio.muted ? {} : {audioCodec: audio.audioCodec, enforceAudioTrack: true}),
  browserExecutable: status.path,
  onBrowserDownload: () => {
    refuseDownload();
  },
});

process.stdout.write(`${JSON.stringify({ok: true, output: job.output, browser: status})}\n`);
