import json
import re
import subprocess
import unittest

# A pasta pessoal da skill vai para um temporário: nenhum teste toca ~/.getbrolls.
import _isolation  # noqa: F401  (efeito de import: define GB_HOME)
from _paths import ROOT

from getbrolls import __version__

PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
COMMANDS = ROOT / "commands"
SETUP_COMMAND = COMMANDS / "scenequarry-setup.md"
REFERENCES = ROOT / "references"


def frontmatter_field(path, field):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} sem frontmatter"
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            return stripped.split(":", 1)[1].strip().strip('"')
    return None


class PluginManifestTests(unittest.TestCase):
    def test_scenequarry_identity_and_origin_are_separate(self):
        plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertEqual("https://github.com/kovr33k/scenequarry", plugin["repository"])
        self.assertEqual(plugin["repository"], plugin["homepage"])
        self.assertEqual("kovr33k", plugin["author"]["name"])
        self.assertEqual("https://github.com/kovr33k", plugin["author"]["url"])
        for name in ("package.json", "package-lock.json"):
            self.assertEqual("scenequarry-tools", json.loads((ROOT / name).read_text(encoding="utf-8"))["name"])
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 Bruno Moreira", license_text)
        self.assertIn("Permission is hereby granted", license_text)
        origin = (ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
        self.assertIn("engenheiro" + "devideo/get" + "-brolls", origin)
        self.assertIn("(MIT)", origin)

    def test_public_tree_has_no_inherited_product_identity_outside_attribution(self):
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
        old_identity = re.compile(r"get" + r"[ -]+b-?rolls|engenheiro" + r"devideo|zbruno" + r"moreira", re.IGNORECASE)
        problems = []
        for name in tracked:
            if not name or name in {"LICENSE", "ATTRIBUTION.md"}:
                continue
            if old_identity.search(name):
                problems.append(name)
                continue
            try:
                content = (ROOT / name).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if old_identity.search(content):
                problems.append(name)
        self.assertEqual([], problems)
        for name in ("brand-logo.png", "flow.svg", "flow.en.svg", "formats.svg", "formats.en.svg"):
            self.assertFalse((ROOT / "assets" / name).exists(), name)

    def test_plugin_manifest_valid(self):
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "scenequarry")
        self.assertEqual(data["version"], __version__)
        for key in ("description", "author", "repository", "license"):
            self.assertIn(key, data)

    def test_marketplace_valid(self):
        data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "kovr33k")
        self.assertIn("name", data["owner"])
        entries = [p for p in data["plugins"] if p["name"] == "scenequarry"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "./")
        self.assertEqual(entries[0].get("version"), __version__)


class SetupCommandTests(unittest.TestCase):
    def test_setup_command_is_discoverable_and_complete(self):
        self.assertTrue(SETUP_COMMAND.is_file(), "commands/scenequarry-setup.md ausente")
        self.assertEqual("scenequarry-setup", frontmatter_field(SETUP_COMMAND, "name"))
        self.assertTrue(frontmatter_field(SETUP_COMMAND, "description"))
        body = SETUP_COMMAND.read_text(encoding="utf-8")
        for marker in (
            '"${CLAUDE_PLUGIN_ROOT}/scripts/install.sh" --check',
            '"${CLAUDE_PLUGIN_ROOT}/scripts/install.ps1"',
            '"${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" doctor',
            "summary",
        ):
            self.assertIn(marker, body, f"passo ausente no comando de setup: {marker}")

    def test_every_command_is_discoverable(self):
        """Todo comando do plugin traz name/description e roda pela raiz do plugin."""
        expected = {
            "scenequarry-setup",
            "scenequarry-brief",
            "scenequarry-eval",
            "scenequarry-status",
            "scenequarry-review",
        }
        found = set()
        for path in sorted(COMMANDS.glob("*.md")):
            name = frontmatter_field(path, "name")
            self.assertEqual(name, path.stem, f"{path.name}: name diverge do arquivo")
            self.assertTrue(frontmatter_field(path, "description"), f"{path.name} sem description")
            found.add(name)
        self.assertEqual(expected, found, "conjunto de comandos do plugin mudou")

    def test_status_command_repasses_the_ready_sentence(self):
        body = (COMMANDS / "scenequarry-status.md").read_text(encoding="utf-8")
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" status --project', body)
        self.assertIn("summary.do.for_human", body)
        self.assertIn("sem parafrasear", body)

    def test_review_command_serves_then_imports(self):
        body = (COMMANDS / "scenequarry-review.md").read_text(encoding="utf-8")
        for marker in (
            '"${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" review --project',
            '"${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" serve --background --project',
            '"${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" import-review --by',
            "127.0.0.1:8767/review.html",
        ):
            self.assertIn(marker, body, f"passo ausente no comando de revisão: {marker}")
        self.assertNotIn("--file", body.split("import-review --by")[1].split("\n")[0])

    def test_plugin_manifest_needs_no_commands_key(self):
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertNotIn("commands", data)


class ReferencesTests(unittest.TestCase):
    """`references/` viaja com o plugin: é de onde o agente tira a copy pronta."""

    EXPECTED = (
        "templates-de-resposta.md",
        "glossario.md",
        "interview.md",
        "providers.md",
        "instagram.md",
        "rights.md",
    )

    def test_reference_files_ship_with_the_plugin(self):
        self.assertTrue(REFERENCES.is_dir(), "pasta references/ ausente")
        for name in self.EXPECTED:
            path = REFERENCES / name
            self.assertTrue(path.is_file(), f"references/{name} ausente")
            self.assertEqual("reference", frontmatter_field(path, "type"))

    def test_providers_reference_keeps_the_two_editorial_guards(self):
        body = (REFERENCES / "providers.md").read_text(encoding="utf-8")
        self.assertIn("Literal primeiro", body)
        self.assertIn("pedir stock explicitamente", body)

    def test_instagram_reference_keeps_the_two_stream_procedure(self):
        body = (REFERENCES / "instagram.md").read_text(encoding="utf-8")
        for marker in (
            "_video.conf",
            "_audio.conf",
            "instagram_pairs.py",
            "--fail-on-duplicate-audio",
            "wait_seconds",
            "--pace 20-60",
            "cooldown",
        ):
            self.assertIn(marker, body, f"procedimento do Instagram perdeu: {marker}")

    def test_every_reference_states_the_path_convention(self):
        """Cada reference é lida sozinha: a regra de caminho vai em cada uma."""
        for name in ("providers.md", "instagram.md", "rights.md"):
            body = (REFERENCES / name).read_text(encoding="utf-8")
            self.assertIn("caminho absoluto da instalação da skill", body, name)
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/gb.py", body, name)
            self.assertIn("--project", body, name)
            self.assertIn("No Windows, use `python`", body, name)

    def test_providers_reference_keeps_the_scan_fallback(self):
        body = (REFERENCES / "providers.md").read_text(encoding="utf-8")
        for marker in ("preview --scan", "GB_SCAN_MAX_SECONDS", "900", "--reference-only"):
            self.assertIn(marker, body, f"providers.md perdeu: {marker}")

    def test_rights_reference_covers_the_three_permit_routes(self):
        body = (REFERENCES / "rights.md").read_text(encoding="utf-8")
        for marker in ("--evidence", "--preset", "--declared-by", "--declaration-text"):
            self.assertIn(marker, body, f"rota de permit ausente: {marker}")

    def test_response_templates_cover_both_approval_routes(self):
        body = (REFERENCES / "templates-de-resposta.md").read_text(encoding="utf-8")
        self.assertIn("Save decisions", body)
        self.assertIn("aprovei todos", body)
        self.assertIn("--channel chat", body)


if __name__ == "__main__":
    unittest.main()
