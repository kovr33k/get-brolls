import {Audio, Sequence, staticFile} from "remotion";

const OWNED_SRC = /^audio\/[A-Za-z0-9][A-Za-z0-9._-]*$/;

const isNonNegInt = (value) => typeof value === "number" && Number.isInteger(value) && value >= 0;

const assertSafeCue = (cue) => {
  if (!cue || typeof cue !== "object") {
    throw new Error("Graphics sound cue is missing.");
  }
  if (typeof cue.id !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(cue.id)) {
    throw new Error("Graphics sound cue needs a safe id.");
  }
  const src = cue.src;
  if (typeof src !== "string" || !OWNED_SRC.test(src)) {
    throw new Error("Graphics sound cue src must be a local audio/<file> path.");
  }
  if (src.includes("..") || src.includes("\\") || src.includes(":") || src.includes("//")) {
    throw new Error("Graphics sound cue src is not a safe local audio path.");
  }
  if (/^(?:https?:|file:|data:)/i.test(src) || src.startsWith("audio/http")) {
    throw new Error("Graphics sound cue cannot use a remote or extra-protocol source.");
  }
  if (!isNonNegInt(cue.start_frame) || !isNonNegInt(cue.trim_before_frame)) {
    throw new Error("Graphics sound cue frames must be nonnegative integers.");
  }
  if (!isNonNegInt(cue.duration_in_frames) || cue.duration_in_frames < 1) {
    throw new Error("Graphics sound cue duration_in_frames must be a positive integer.");
  }
  if (typeof cue.gain !== "number" || !Number.isFinite(cue.gain) || cue.gain < 0) {
    throw new Error("Graphics sound cue gain must be a finite number.");
  }
  if (cue.vo != null || cue.source_ref != null || cue.kind === "full_recording") {
    throw new Error("Graphics render cannot include voice-over.");
  }
};

export const GraphicsAudio = ({sound_cues}) => {
  const cues = Array.isArray(sound_cues) ? sound_cues : [];
  return (
    <>
      {cues.map((cue) => {
        assertSafeCue(cue);
        return (
          <Sequence key={cue.id} from={cue.start_frame} durationInFrames={cue.duration_in_frames}>
            <Audio
              src={staticFile(cue.src)}
              trimBefore={cue.trim_before_frame}
              durationInFrames={cue.duration_in_frames}
              volume={cue.gain}
            />
          </Sequence>
        );
      })}
    </>
  );
};
