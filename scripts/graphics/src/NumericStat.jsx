import {cancelRender, continueRender, delayRender, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {GraphicsAudio} from "./GraphicsAudio.jsx";
import {GraphicsBackground} from "./GraphicsBackground.jsx";

const fontHandle = delayRender("ibm-plex-sans");

const loadLocalFonts = async () => {
  try {
    if (typeof FontFace === "undefined" || !document?.fonts) {
      throw new Error("Local font loader is unavailable; IBM Plex Sans cannot be loaded from publicDir.");
    }
    const regular = new FontFace(
      "IBM Plex Sans",
      `url(${staticFile("fonts/ibm-plex-sans-latin-400-normal.woff")}) format("woff")`,
      {weight: "400", style: "normal", display: "block"},
    );
    const bold = new FontFace(
      "IBM Plex Sans",
      `url(${staticFile("fonts/ibm-plex-sans-latin-700-normal.woff")}) format("woff")`,
      {weight: "700", style: "normal", display: "block"},
    );
    const loaded = await Promise.all([regular.load(), bold.load()]);
    loaded.forEach((face) => document.fonts.add(face));
    continueRender(fontHandle);
  } catch (error) {
    cancelRender(error);
  }
};

loadLocalFonts();

const paper = "#e6dccb";
const ink = "#16130f";
const mutedPaper = "#d5c9b5";
const accent = "#b8874a";
const rule = "#2a241c";

const progress = (frame, durationInFrames, startFrac, endFrac) => {
  if (durationInFrames <= 1) {
    return 1;
  }
  const last = durationInFrames - 1;
  const start = Math.floor(startFrac * last);
  const end = Math.max(start + 1, Math.min(last, Math.ceil(endFrac * last)));
  return interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

export const NumericStat = ({value, unit, label, claim_status, claim_note, narration, timing_basis, sound_cues = [], background = null}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const intro = progress(frame, durationInFrames, 0, 0.22);
  const numberIn = progress(frame, durationInFrames, 0.12, 0.42);
  const unitIn = progress(frame, durationInFrames, 0.28, 0.58);
  const noteIn = progress(frame, durationInFrames, 0.45, 0.85);
  const estimated = timing_basis === "estimated";
  const hasBackground = Boolean(background);
  const claim =
    claim_status === "synthetic"
      ? "Synthetic draft value"
      : claim_status === "sourced"
        ? "Sourced from recorded evidence"
        : "Unverified scenario claim";
  const extraNote =
    claim_note && claim_note.replace(/\.$/, "") !== claim ? ` · ${claim_note}` : "";
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: hasBackground ? "transparent" : ink,
        color: paper,
        fontFamily: '"IBM Plex Sans", sans-serif',
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <GraphicsBackground background={background} />
      <GraphicsAudio sound_cues={sound_cues} />
      <div
        style={{
          width: 1480,
          border: `1px solid ${rule}`,
          background: hasBackground ? "rgba(28, 24, 19, 0.78)" : "#1c1813",
          padding: "72px 88px 80px",
          opacity: intro,
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            fontSize: 28,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: accent,
            marginBottom: 28,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontVariantNumeric: "tabular-nums",
            fontWeight: 700,
            fontSize: 220,
            lineHeight: 0.9,
            letterSpacing: "-0.04em",
            transform: `translateY(${(1 - numberIn) * 24}px)`,
            opacity: numberIn,
          }}
        >
          {value}
        </div>
        <div
          style={{
            marginTop: 18,
            fontSize: 42,
            color: paper,
            opacity: unitIn,
            borderTop: `1px solid ${rule}`,
            paddingTop: 18,
            letterSpacing: "0.04em",
          }}
        >
          {unit}
        </div>
        <div
          style={{
            marginTop: 34,
            color: mutedPaper,
            fontSize: 28,
            maxWidth: 1200,
            opacity: noteIn,
            whiteSpace: "pre-wrap",
          }}
        >
          {narration}
        </div>
        <div
          style={{
            marginTop: 40,
            fontSize: 22,
            color: accent,
            opacity: noteIn,
          }}
        >
          {claim_status === "sourced" ? claim_note || claim : claim}
          {claim_status === "sourced" ? "" : extraNote}
          {estimated ? " · Estimated draft timing" : ""}
        </div>
      </div>
    </div>
  );
};
