"""Build a reproducible static review inventory; this scanner does not prove absence of exfiltration."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


class NetworkAuditInventory:
    """Inventory source, network sinks, downloads, subprocesses, and installed dependencies."""

    _URL = re.compile(r"https?://[^\s<>\"'`\\)\]}]+")
    _SIGNALS = {
        "telemetry": re.compile(r"\b(?:telemetry|sentry|posthog|sendBeacon|opentelemetry|analytics|monitoring)\b", re.I),
        "transfer": re.compile(r"\b(?:upload|webhook|scp|rsync|smtplib|ftplib)\b", re.I),
        "execution_or_deserialisation": re.compile(r"\b(?:eval|exec|pickle\.load|load_pickle|Popen|subprocess_run|os\.system)\b"),
        "agent_disclosure_instruction": re.compile(
            r"(?:send|share|report|submit|upload).{0,100}(?:third.party|external|developer|issue|log|code|data)", re.I
        ),
    }
    _CALL = re.compile(
        r"(?:requests(?:_lib)?\.|httpx\.|urllib\.|socket\.|subprocess\.|\.urlopen$|\.urlretrieve$|"
        r"\.download|^subprocess_run$|^os\.(?:system|popen)$|\.Session$|\.Client$|"
        r"_session\.(?:get|post|request|send)$|\.open$|\.connect$|\.sendall$|"
        r"build_npm_install_command|load_pickle|load_cached_values|load_cache|\.load_file$)"
    )

    def __init__(self, root: Path):
        self._root = root.resolve()

    @staticmethod
    def _group(path: str) -> str:
        if path.startswith("src/solidlsp/language_servers/"):
            return "language_server_adapter"
        if path.startswith(("src/selene/resources/config/", ".selene/memories/")) or path in {"AGENTS.md", "CLAUDE.md"}:
            return "agent_instructions"
        if path.startswith("src/selene/resources/dashboard/"):
            return "dashboard_asset"
        if path.startswith("src/"):
            return "runtime"
        if path.startswith("test/"):
            return "test_or_fixture"
        if path.startswith(".github/"):
            return "ci_or_repository_automation"
        if path.startswith(("docs/", "resources/")) or path.endswith(".md"):
            return "documentation_or_artwork"
        return "build_configuration_or_script"

    @classmethod
    def _inspect_text(cls, text: str) -> dict:
        signals = {}
        for category, pattern in cls._SIGNALS.items():
            lines = [n for n, line in enumerate(text.splitlines(), 1) if pattern.search(line)]
            if lines:
                signals[category] = lines
        domains = set()
        for match in cls._URL.finditer(text):
            try:
                host = urlsplit(match[0]).hostname
                if host:
                    domains.add(host)
            except ValueError:
                # incomplete URLs in examples and format strings are review candidates too
                domains.add("<dynamic-or-incomplete-url>")
        return {"domains": sorted(domains), "signal_lines": signals}

    def repository(self) -> dict:
        # include renamed/untracked source while respecting generated-file exclusions
        paths = (
            subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=self._root)
            .decode()
            .split("\0")
        )
        files = []
        for name in sorted(set(paths) - {""}):
            if name.startswith("security/") or name == "SECURITY_AUDIT.md":
                continue
            path = self._root / name
            if not path.is_file():
                continue
            raw = path.read_bytes()
            entry = {"path": name, "category": self._group(name), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                entry["binary"] = True
                files.append(entry)
                continue
            entry.update(self._inspect_text(text))
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                    entry["candidate_calls"] = [
                        {"line": node.lineno, "function": ast.unparse(node.func)}
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and self._CALL.search(ast.unparse(node.func))
                    ]
                except SyntaxError as exc:
                    entry["parse_error"] = str(exc)
            files.append(entry)
        return {
            "scope": "Current checkout excluding Git history, ignored/generated files, and the security reports themselves",
            "meaning": "Candidate locations for human review, not a security verdict. URLs can be inert documentation or fixture strings.",
            "file_count": len(files),
            "categories": dict(Counter(f["category"] for f in files)),
            "files": files,
        }

    def dependencies(self) -> dict:
        distributions = []
        for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
            hits = []
            file_count = 0
            fingerprint = hashlib.sha256()
            for relative in sorted(dist.files or [], key=str):
                if relative.suffix not in {".py", ".js", ".pth"}:
                    continue
                path = Path(dist.locate_file(relative))
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                fingerprint.update(str(relative).encode() + b"\0" + hashlib.sha256(raw).digest())
                file_count += 1
                try:
                    result = self._inspect_text(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
                if result["domains"] or result["signal_lines"]:
                    hits.append({"path": str(relative), **result})
            distributions.append(
                {
                    "name": dist.metadata["Name"],
                    "version": dist.version,
                    "text_files_scanned": file_count,
                    "source_fingerprint": fingerprint.hexdigest(),
                    "candidate_files": hits,
                }
            )
        return {
            "scope": "Installed packages for this platform, including optional integrations and development tools; Python/JS/PTH text only",
            "meaning": "Static signal inventory. Compiled extensions, unavailable platform wheels, remotely installed language servers, and provider infrastructure are not exhaustively audited.",
            "distribution_count": len(distributions),
            "distributions": distributions,
        }

    def write(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for name, data in [("repository-inventory.json", self.repository()), ("dependency-inventory.json", self.dependencies())]:
            (destination / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Wrote {destination / name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("security"))
    args = parser.parse_args()
    NetworkAuditInventory(Path(__file__).resolve().parents[1]).write(args.output)
