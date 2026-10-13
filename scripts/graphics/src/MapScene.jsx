import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import "./LocalFonts.jsx";
import {GraphicsAudio} from "./GraphicsAudio.jsx";
import {GraphicsBackground} from "./GraphicsBackground.jsx";

const polygonPath = (polygon, project) => polygon.map(ring => ring.map((point, i) => `${i ? "L" : "M"}${project(point).join(",")}`).join(" ") + " Z").join(" ");
const path = (geometry, project) => (geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates).map(p => polygonPath(p, project)).join(" ");
const labelLines = label => label.match(/.{1,25}(?:\s|$)|.{1,25}/g).map(line => line.trim());

export const MapScene = ({scene, claim_status, timing_basis, sound_cues = [], background = null}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const movement = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const box = scene.bounds.map((n, i) => n + (scene.focus[i] - n) * movement);
  const scale = Math.min(1260 / (box[2] - box[0]), 540 / (box[3] - box[1]));
  const project = ([lon, lat]) => [840 + (lon - (box[0] + box[2]) / 2) * scale, 340 - (lat - (box[1] + box[3]) / 2) * scale];
  return <div style={{width: "100%", height: "100%", background: "#16130f", color: "#e6dccb", fontFamily: '"IBM Plex Sans", sans-serif'}}>
    <GraphicsBackground background={background} /><GraphicsAudio sound_cues={sound_cues} />
    <div style={{position: "absolute", inset: "76px 120px"}}>
      <p style={{fontSize: 28, color: "#b8874a", letterSpacing: 4}}>GEOGRAPHY</p>
      <h1 style={{fontSize: scene.title.length > 90 ? 30 : scene.title.length > 65 ? 42 : 58, lineHeight: 1.12, height: 110, overflowWrap: "anywhere", margin: "0 0 22px"}}>{scene.title}</h1>
      <svg width="1680" height="660" viewBox="0 0 1680 660" style={{background: "#1c1813", border: "1px solid #554534"}}>
        {scene.layers.map((layer, i) => {
          const beat = scene.beats[i];
          const reveal = interpolate(frame, [beat.at_frame, beat.at_frame + 10], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          const claimed = layer.treatment === "claim";
          const illustrative = layer.treatment === "illustrative";
          const [x, y] = project(layer.label_point);
          const lines = labelLines(beat.label);
          const fontSize = scene.layers.length > 4 ? 24 : 30;
          const labelX = Math.max(390, Math.min(1290, x));
          const labelY = Math.max(55, Math.min(560 - (lines.length - 1) * 36, y));
          const [px, py] = illustrative ? project(layer.geometry.coordinates) : [0, 0];
          return <g key={beat.id} opacity={reveal}>
            {illustrative ? <circle cx={px} cy={py} r="10" fill="none" stroke="#e7b66b" strokeWidth="3" /> : <path d={path(layer.geometry, project)} fill={claimed ? "rgba(231,182,107,0.15)" : "#39433e"} fillRule="evenodd" stroke={claimed ? "#e7b66b" : "#b8c5bb"} strokeWidth={claimed ? 3 : 2} strokeDasharray={claimed ? "10 7" : undefined} />}
            <text x={labelX} y={labelY} textAnchor="middle" fontSize={fontSize} fill="#e6dccb" stroke="#1c1813" strokeWidth="5" paintOrder="stroke">{lines.map((line, index) => <tspan key={index} x={labelX} dy={index ? 36 : 0}>{line}</tspan>)}</text>
          </g>;
        })}
        <g transform="translate(36 612)" fontSize="22" fill="#baaf9c">
          <text>Solid: selected geography / recognized border · Dashed amber: claim · Hollow marker: illustration, not a real site</text>
        </g>
      </svg>
      <p style={{fontSize: 22, lineHeight: 1.3, color: "#b8874a"}}>{scene.caption} · {claim_status === "synthetic" ? "Synthetic geography" : "Selected source geometry; treatments follow saved evidence"} · Equirectangular framing, not an area measurement.</p>
    </div>
    {timing_basis === "estimated" ? <div style={{position: "absolute", top: 28, right: 120, fontSize: 22, color: "#e7b66b"}}>Estimated draft · no narration timing</div> : null}
  </div>;
};
