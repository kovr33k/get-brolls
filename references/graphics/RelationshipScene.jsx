// Authored example: documented organizational responsibility, not a physical route.
import {interpolate, useCurrentFrame} from "remotion";

export const AuthorScene = ({scene, claim_status}) => {
  const frame = useCurrentFrame();
  const positions = [[840, 110], [390, 420], [1290, 420]];
  return <div style={{position: "absolute", inset: "96px 120px"}}>
    <p style={{fontSize: 28, color: "#b8874a", letterSpacing: 4}}>RELATIONSHIPS · CONCEPTUAL</p>
    <h1 style={{fontSize: scene.title.length > 90 ? 30 : scene.title.length > 65 ? 42 : 58, lineHeight: 1.12, height: 148, overflowWrap: "anywhere"}}>{scene.title}</h1>
    <svg width="1680" height="590" viewBox="0 0 1680 590">
      <defs><marker id="relation-arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#b8874a" /></marker></defs>
      {scene.beats.slice(1).map((beat, i) => {
        const reveal = interpolate(frame, [beat.at_frame, beat.at_frame + 14], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        return <path key={beat.id} d={`M840 168 L${positions[i + 1][0]} 355`} fill="none" stroke="#b8874a" strokeWidth="3" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - reveal} markerEnd="url(#relation-arrow)" opacity={reveal} />;
      })}
      {scene.beats.map((beat, i) => {
        const reveal = interpolate(frame, [beat.at_frame, beat.at_frame + 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        const [x, y] = positions[i];
        return <g key={beat.id} opacity={reveal}>
          <rect x={x - 315} y={y - 55} width="630" height="110" rx="18" fill="#1c1813" stroke="#554534" strokeWidth="2" />
          <text x={x} y={y + 10} fill="#e6dccb" textAnchor="middle" fontSize="30">{beat.label}</text>
        </g>;
      })}
    </svg>
    <p style={{fontSize: 24, lineHeight: 1.35, color: "#b8874a"}}>{scene.caption} · Arrows express the stated relationship, not transport, flight paths or money flows.{claim_status === "synthetic" ? " Synthetic example." : ""}</p>
  </div>;
};
