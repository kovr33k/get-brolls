// Authored example: conceptual dilution stages, not measured equipment or flow.
import {interpolate, useCurrentFrame} from "remotion";

export const AuthorScene = ({scene, claim_status}) => {
  const frame = useCurrentFrame();
  const visible = scene.beats.map(beat => interpolate(frame, [beat.at_frame, beat.at_frame + 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}));
  const mixed = visible[2] ?? 0;
  return <div style={{position: "absolute", inset: "96px 120px"}}>
    <p style={{fontSize: 28, color: "#b8874a", letterSpacing: 4}}>PROCESS · CONCEPTUAL</p>
    <h1 style={{fontSize: scene.title.length > 90 ? 30 : scene.title.length > 65 ? 42 : 58, lineHeight: 1.12, height: 148, overflowWrap: "anywhere"}}>{scene.title}</h1>
    <svg width="1680" height="510" viewBox="0 0 1680 510">
      <path d="M120 305 L760 305 L760 235 L1450 235" stroke="#554534" strokeWidth="50" fill="none" strokeLinejoin="round" />
      <path d="M120 305 L760 305 L760 235 L1450 235" stroke="#8a6540" strokeWidth={42 - 17 * mixed} fill="none" strokeLinejoin="round" strokeDasharray="58 22" strokeDashoffset={-frame * (1 + mixed)} opacity={visible[0]} />
      <path d="M760 90 L760 280" stroke="#e7b66b" strokeWidth="14" fill="none" strokeDasharray="24 14" strokeDashoffset={-frame * 2} opacity={visible[1] ?? 0} />
      <circle cx="760" cy="280" r="60" fill="#1c1813" stroke="#b8874a" strokeWidth="3" opacity={mixed} />
      <path d="M730 260 L790 300 M790 260 L730 300" stroke="#e7b66b" strokeWidth="6" opacity={mixed} transform={`rotate(${frame * 2} 760 280)`} />
      {scene.beats.map((beat, i) => <g key={beat.id} opacity={visible[i]}>
        <text x={[220, 760, 900, 1370][i] ?? 1370} y={[430, 65, 410, 145][i] ?? 430} textAnchor="middle" fill="#e6dccb" fontSize="30">{beat.label}</text>
      </g>)}
    </svg>
    <p style={{fontSize: 24, lineHeight: 1.35, color: "#b8874a"}}>{scene.caption} · No measured ratio, flow speed or equipment layout is implied.{claim_status === "synthetic" ? " Synthetic example." : ""}</p>
  </div>;
};
