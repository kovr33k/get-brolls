import {Composition} from "remotion";
import {CustomScene} from "./CustomScene.jsx";
export const Root = () => <Composition id="CustomScene" component={CustomScene} width={1920} height={1080} fps={30} durationInFrames={90} />;
