"""Build a standalone Selene plugin directory and ZIP from this checkout."""

import argparse
import json
import shutil
from pathlib import Path


class PluginBuilder:
    """Assembler of the runtime files required by the Selene agent plugin."""

    _INCLUDED_PATHS = (
        "plugin.json",
        "mcp.json",
        ".codex-plugin",
        ".claude-plugin",
        ".github/plugin",
        ".agents/plugins",
        "skills",
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "README.md",
        "PLUGIN.md",
        "src/selene",
        "src/interprompt",
        "src/solidlsp",
    )

    def __init__(self, source: Path):
        """Initialize the builder for a Selene checkout."""
        self._source = source.resolve()

    def build(self, destination: Path) -> Path:
        """Create the plugin directory and return its ZIP path.

        :param destination: new directory whose name matches the plugin name
        :raises FileExistsError: if either output already exists
        """
        # validate inputs before creating output
        destination = destination.resolve()
        manifest = json.loads((self._source / "plugin.json").read_text())
        if destination.name != manifest["name"]:
            raise ValueError(f"The output directory must be named {manifest['name']!r}.")
        archive = destination.with_suffix(".zip")
        for output in (destination, archive):
            if output.exists():
                raise FileExistsError(f"Output already exists: {output}. Choose a new parent directory.")
        for relative_path in self._INCLUDED_PATHS:
            source = self._source / relative_path
            if not source.exists():
                raise FileNotFoundError(source)
            if destination.is_relative_to(source):
                raise ValueError(f"Output cannot be inside a packaged source directory: {source}")

        # assemble runtime inputs without development state or local configuration
        destination.mkdir(parents=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".env", ".env.*", ".git", ".selene", ".venv")
        for relative_path in self._INCLUDED_PATHS:
            source = self._source / relative_path
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=ignore)
            else:
                shutil.copy2(source, target)

        # archive the self-contained plugin under its canonical directory name
        shutil.make_archive(str(destination), "zip", root_dir=destination.parent, base_dir=destination.name)
        return archive


if __name__ == "__main__":
    # accept a destination independent of the caller's working directory
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "dist" / "selene", help="New plugin directory (must be named selene).")
    arguments = parser.parse_args()
    result = PluginBuilder(root).build(arguments.output)
    print(f"Plugin directory: {arguments.output.resolve()}")
    print(f"Plugin archive: {result}")
