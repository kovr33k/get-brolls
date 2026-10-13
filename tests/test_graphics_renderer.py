"""An explicit prepared browser must be used while selecting as well as rendering."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT


class PreparedBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_composition_selection_does_not_fall_back_to_package_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "render.mjs").write_bytes((ROOT / "scripts/graphics/render.mjs").read_bytes())
            browser = root / "prepared-browser.exe"
            browser.write_bytes(b"Synthetic prepared-browser path; no executable is launched.")
            modules = {
                "bundler": "export async function bundle() {return 'http://127.0.0.1/synthetic-bundle';}",
                "renderer": """import fs from 'node:fs';
let prepared;
export async function ensureBrowser(options) {
  prepared = options.browserExecutable;
  if (!prepared) throw new Error('This fixture has no default browser');
  return {path:prepared, type:'chrome-headless-shell'};
}
export async function selectComposition(options) {
  if (options.browserExecutable !== prepared) throw new Error('Package browser fallback attempted');
  let blocked = false;
  try {options.onBrowserDownload();} catch {blocked = true;}
  if (!blocked) throw new Error('Selection may download a browser');
  return {id:options.id, selectedBrowser:options.browserExecutable};
}
export async function renderMedia(options) {
  if (options.browserExecutable !== prepared) throw new Error('Render browser changed');
  fs.writeFileSync(options.outputLocation, JSON.stringify(options.composition));
}
""",
            }
            for name, source in modules.items():
                module = root / "node_modules/@remotion" / name
                module.mkdir(parents=True)
                (module / "package.json").write_text(json.dumps({"type": "module", "exports": "./index.mjs"}))
                (module / "index.mjs").write_text(source)
            job = {
                "browserExecutable": str(browser),
                "composition": "CustomScene",
                "entry": "source/index.jsx",
                "publicDir": "public",
                "props": {},
                "output": str(root / "observed.json"),
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "durationInFrames": 90,
                "codec": "h264",
                "pixelFormat": "yuv420p",
                "colorSpace": "bt709",
                "imageFormat": "png",
            }
            (root / "job.json").write_text(json.dumps(job))
            done = subprocess.run(
                ["node", "render.mjs", "--job", "job.json"], cwd=root, capture_output=True, text=True, check=False
            )
            self.assertEqual(0, done.returncode, done.stderr)
            observed = json.loads((root / "observed.json").read_text())
            self.assertEqual(str(browser), observed["selectedBrowser"])
            self.assertEqual("CustomScene", observed["id"])
