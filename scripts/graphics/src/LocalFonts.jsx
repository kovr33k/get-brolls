import {cancelRender, continueRender, delayRender, staticFile} from "remotion";

const handle = delayRender("timeline-local-fonts");
const load = async () => {
  try {
    const faces = await Promise.all([400, 700].map(async (weight) => {
      const face = new FontFace("IBM Plex Sans", `url(${staticFile("fonts/ibm-plex-sans-latin-" + weight + "-normal.woff")}) format("woff")`, {weight: String(weight)});
      return face.load();
    }));
    faces.forEach((face) => document.fonts.add(face));
    continueRender(handle);
  } catch (error) {
    cancelRender(error);
  }
};
load();
