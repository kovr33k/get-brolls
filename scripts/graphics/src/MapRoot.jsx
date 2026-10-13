import {Composition} from "remotion";
import {MapScene} from "./MapScene.jsx";
export const Root = () => <Composition id="MapScene" component={MapScene} width={1920} height={1080} fps={30} durationInFrames={90} />;
