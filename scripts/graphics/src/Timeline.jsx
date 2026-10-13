import {interpolate, useCurrentFrame} from "remotion";
import "./LocalFonts.jsx";
import {GraphicsAudio} from "./GraphicsAudio.jsx";
import {GraphicsBackground} from "./GraphicsBackground.jsx";

export const Timeline = ({title, milestones, claim_status, claim_note, timing_basis, sound_cues = [], background = null}) => {
  const frame = useCurrentFrame();
  const active = milestones.reduce((found, item, index) =>
    item.at_frame !== null && item.at_frame <= frame ? index : found, -1);
  const intro = interpolate(frame, [0, 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <div style={{width: "100%", height: "100%", position: "relative", background: "#16130f", color: "#e6dccb", fontFamily: '"IBM Plex Sans", sans-serif'}}>
      <GraphicsBackground background={background} />
      <GraphicsAudio sound_cues={sound_cues} />
      <div style={{position: "absolute", inset: "96px 120px", padding: 54, background: background ? "rgba(28,24,19,0.82)" : "#1c1813", border: "1px solid #2a241c", opacity: intro}}>
        <div style={{fontSize: 30, color: "#b8874a", letterSpacing: "0.08em"}}>CHRONOLOGY</div>
        <h1 style={{fontSize: title.length > 60 ? 44 : 62, lineHeight: 1.1, height: 164, margin: "18px 0 28px", overflowWrap: "anywhere"}}>{title}</h1>
        <div style={{display: "grid", gridTemplateColumns: `repeat(${Math.max(1, milestones.length)}, 1fr)`, gap: 20, position: "relative"}}>
          <div style={{position: "absolute", top: 171, left: 0, right: 0, height: 2, background: "#554534"}} />
          {milestones.map((item, index) => {
            const highlighted = index === active;
            return <div key={item.id} data-milestone={item.id} data-active={highlighted} style={{position: "relative", color: highlighted ? "#e6dccb" : "#baaf9c"}}>
              <div style={{fontSize: milestones.length > 4 || (milestones.length > 3 && item.date.length > 35) ? 26 : 38, fontWeight: 700, height: 145, lineHeight: 1.15, overflowWrap: "anywhere", fontVariantNumeric: "tabular-nums", color: highlighted ? "#e7b66b" : "#baaf9c"}}>{item.date}</div>
              <div style={{margin: "14px 0 30px", width: 20, height: 20, borderRadius: 10, background: highlighted ? "#e7b66b" : "#554534", boxShadow: highlighted ? "0 0 0 8px rgba(184,135,74,0.20)" : "none"}} />
              <div style={{fontSize: milestones.length > 4 ? 26 : 30, lineHeight: 1.25, overflowWrap: "anywhere"}}>{item.label}</div>
            </div>;
          })}
        </div>
        <p style={{position: "absolute", bottom: 30, left: 54, right: 54, fontSize: 22, color: "#b8874a"}}>{claim_status === "synthetic" ? "Synthetic dated milestones" : claim_status === "sourced" ? claim_note || "Dates and labels tied to saved evidence" : "Unverified scenario dates"}{timing_basis === "estimated" ? " · Estimated draft timing" : ""} · Spacing is illustrative; no event duration implied.</p>
      </div>
    </div>
  );
};
