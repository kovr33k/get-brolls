import {cancelRender, Img, OffthreadVideo, staticFile} from "remotion";

const OWNED_SRC = /^media\/[A-Za-z0-9][A-Za-z0-9._-]*$/;

const isNonNegInt = (value) => typeof value === "number" && Number.isInteger(value) && value >= 0;

const assertSafeBackground = (background) => {
  if (!background || typeof background !== "object") {
    throw new Error("Graphics background is missing.");
  }
  if (background.kind !== "video" && background.kind !== "image") {
    throw new Error("Graphics background kind must be video or image.");
  }
  const src = background.src;
  if (typeof src !== "string" || !OWNED_SRC.test(src)) {
    throw new Error("Graphics background src must be a local media/<file> path.");
  }
  if (src.includes("..") || src.includes("\\") || src.includes(":") || src.includes("//")) {
    throw new Error("Graphics background src is not a safe local media path.");
  }
  if (/^(?:https?:|file:|data:)/i.test(src) || src.startsWith("media/http")) {
    throw new Error("Graphics background cannot use a remote or extra-protocol source.");
  }
  if (src.includes("narration/private") || src.includes("previews/") || src.includes("clips/")) {
    throw new Error("Graphics background cannot use a private or unfrozen source path.");
  }
  if (background.fit !== "contain" && background.fit !== "cover") {
    throw new Error("Graphics background fit must be contain or cover.");
  }
  if (!isNonNegInt(background.trim_before)) {
    throw new Error("Graphics background trim_before must be a nonnegative integer.");
  }
  if (!isNonNegInt(background.duration_in_frames) || background.duration_in_frames < 1) {
    throw new Error("Graphics background duration_in_frames must be a positive integer.");
  }
  if (!isNonNegInt(background.width) || background.width < 1 || !isNonNegInt(background.height) || background.height < 1) {
    throw new Error("Graphics background width and height must be actual positive integers.");
  }
  if (background.muted !== true) {
    throw new Error("Graphics background source audio must stay muted.");
  }
  if (background.vo != null || background.volume) {
    throw new Error("Graphics render cannot include background audio or voice-over.");
  }
};

export const GraphicsBackground = ({background}) => {
  if (background == null) {
    return null;
  }
  assertSafeBackground(background);
  const objectFit = background.fit === "cover" ? "cover" : "contain";
  const style = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit,
  };
  const fail = (error) => {
    cancelRender(error);
  };
  if (background.kind === "image") {
    return <Img src={staticFile(background.src)} style={style} onError={fail} />;
  }
  return (
    <OffthreadVideo
      src={staticFile(background.src)}
      muted
      trimBefore={background.trim_before}
      durationInFrames={background.duration_in_frames}
      style={style}
      onError={fail}
    />
  );
};
