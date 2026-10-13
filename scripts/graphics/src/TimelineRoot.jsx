import {Composition} from "remotion";
import {Timeline} from "./Timeline.jsx";

export const Root = () => (
  <Composition id="Timeline" component={Timeline} width={1920} height={1080} fps={30} durationInFrames={90}
    defaultProps={{title: "Synthetic chronology", milestones: [], narration: "", claim_status: "synthetic", timing_basis: "estimated"}} />
);
