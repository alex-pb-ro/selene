"""Prepare an offline verifier build context from installed, platform-independent tools."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path


class VerifierBuildContext:
    """Copy only the verifier and explicit dependencies, excluding projects and credentials."""

    @staticmethod
    def create(output: Path, typescript: Path) -> dict:
        output.mkdir(parents=True, exist_ok=False)
        dependencies = output / "dependencies"
        dependencies.mkdir()
        versions = {}
        for name in ("pytest", "pluggy", "iniconfig", "packaging", "pygments"):
            distribution = importlib.metadata.distribution(name)
            versions[name] = distribution.version
            for entry in distribution.files or ():
                if ".." in entry.parts or entry.suffix == ".pyc":
                    continue
                source = Path(str(distribution.locate_file(entry)))
                if not source.is_file():
                    continue
                if source.suffix in {".so", ".dylib", ".pyd"}:
                    raise ValueError("Verifier dependencies must be platform-independent")
                target = dependencies / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        shutil.copytree(typescript.resolve(strict=True), output / "typescript", ignore=shutil.ignore_patterns("node_modules"))
        versions["typescript"] = json.loads((typescript / "package.json").read_text())["version"]
        for name in ("checks.py", "container_worker.py", "Verifier.Dockerfile"):
            shutil.copyfile(Path(__file__).with_name(name), output / name)
        hashes = {
            path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        manifest = {"versions": versions, "files_sha256": hashes, "network_installation": False}
        (output / "tooling.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return {"build_context": str(output.resolve()), "versions": versions, "files": len(hashes)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--typescript", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(VerifierBuildContext.create(args.output, args.typescript), indent=2))
