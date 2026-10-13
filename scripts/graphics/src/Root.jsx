import {Composition} from "remotion";
import {NumericStat} from "./NumericStat.jsx";

const DEFAULT_PROPS = {
  value: "—",
  unit: "units",
  label: "Synthetic numeric draft",
  claim_status: "synthetic",
  claim_note: "Synthetic draft value.",
  narration: "",
  timing_basis: "estimated",
};

export const Root = () => {
  return (
    <Composition
      id="NumericStat"
      component={NumericStat}
      durationInFrames={90}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={DEFAULT_PROPS}
    />
  );
};
