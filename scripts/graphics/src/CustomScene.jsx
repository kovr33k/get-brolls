import "./LocalFonts.jsx";
import {AuthorScene} from "./AuthorScene.jsx";
import {GraphicsAudio} from "./GraphicsAudio.jsx";
import {GraphicsBackground} from "./GraphicsBackground.jsx";

export const CustomScene = (props) => <div style={{width: "100%", height: "100%", position: "relative", background: "#16130f", color: "#e6dccb", fontFamily: '"IBM Plex Sans", sans-serif'}}>
  <GraphicsBackground background={props.background ?? null} />
  <GraphicsAudio sound_cues={props.sound_cues ?? []} />
  <AuthorScene {...props} />
  {props.timing_basis === "estimated" ? <div style={{position: "absolute", bottom: 18, left: 120, fontSize: 22, color: "#e7b66b"}}>Estimated draft · no narration timing</div> : null}
</div>;
