"""Observe persistent source copies using a synthetic file and an installed Pyright."""

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


class CacheDataAudit:
    CANARY = "SYNTHETIC_COMMENT_OUTSIDE_REQUESTED_SYMBOL_ONLY"

    def run(self, node: str, pyright_script: str) -> None:
        base = Path(tempfile.mkdtemp(prefix="selene-cache-data-"))
        os.environ["SELENE_HOME"] = str(base / "home")

        from solidlsp import SolidLanguageServer
        from solidlsp.ls_config import LanguageServerConfig, LanguageServerId
        from solidlsp.settings import SolidLSPSettings

        project = base / "project"
        project.mkdir()
        source = f"# {self.CANARY}\n\ndef example():\n    return 42\n"
        (project / "sample.py").write_text(source)
        (project / "pyrightconfig.json").write_text('{"include": ["sample.py"]}')
        guard = Path(__file__).with_name("node-network-guard.cjs").resolve()
        network_log = base / "network.jsonl"
        network_log.write_text("")
        os.environ["NODE_OPTIONS"] = "--require=" + str(guard)
        os.environ["SELENE_NETWORK_AUDIT_LOG"] = str(network_log)
        settings = SolidLSPSettings(
            solidlsp_dir=str(base / "lsp-home"),
            project_data_path=str(project / ".selene"),
            ls_specific_settings={"python": {"ls_base_cmd": [node, pyright_script], "ls_args": ["--stdio"]}},
        )
        previous_umask = os.umask(0o022)
        ls = None
        try:
            ls = SolidLanguageServer.create(
                LanguageServerConfig(ls_id=LanguageServerId.PYTHON), str(project), solidlsp_settings=settings, timeout=30
            )
            ls.start()
            symbols = ls.request_document_symbols("sample.py")
            body = symbols.root_symbols[0]["body"].get_text()
            ls.save_cache()
            cache = ls.cache_dir / ls.DOCUMENT_SYMBOL_CACHE_FILENAME
            report = {
                "requested_symbol_body": body,
                "canary_outside_symbol": self.CANARY not in body,
                "outside_symbol_comment_persisted_in_cache": self.CANARY.encode() in cache.read_bytes(),
                "cache_file_mode": oct(stat.S_IMODE(cache.stat().st_mode)),
                "cache_path": str(cache),
                "source_removed_cache_persists": False,
                "pyright_script": pyright_script,
                "pyright_script_sha256": hashlib.sha256(Path(pyright_script).read_bytes()).hexdigest(),
                "network_attempts": [json.loads(line) for line in network_log.read_text().splitlines()],
                "scope": "Real Pyright 1.1.403, synthetic source, Node network hooks enabled; not an OS-wide capture.",
            }
            (project / "sample.py").unlink()
            report["source_removed_cache_persists"] = self.CANARY.encode() in cache.read_bytes()
        finally:
            if ls is not None:
                ls.stop()
            os.umask(previous_umask)

        output = Path(__file__).resolve().parents[1] / "cache-data-verification.json"
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("node")
    parser.add_argument("pyright_script")
    args = parser.parse_args()
    CacheDataAudit().run(args.node, args.pyright_script)
