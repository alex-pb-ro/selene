"""Synthetic native/Linux metadata, partial-failure and exchange-race verification."""

import argparse
import ctypes
import hashlib
import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from selene.changes.model import ProposedFileChange
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.edit_plans.service import RecoverableChanges
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


class MetadataCanary:
    def __init__(self):
        self.name = b"com.selene.probe" if platform.system() == "Darwin" else b"user.selene_probe"

    def set(self, path: Path) -> None:
        if platform.system() != "Darwin":
            os.setxattr(path, self.name, b"metadata-canary")
            return
        function = ctypes.CDLL(None, use_errno=True).fsetxattr
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        function.restype = ctypes.c_int
        with path.open("rb") as stream:
            assert function(stream.fileno(), self.name, b"metadata-canary", 15, 0, 0) == 0

    def read(self, path: Path) -> bytes:
        if platform.system() != "Darwin":
            return os.getxattr(path, self.name)
        function = ctypes.CDLL(None, use_errno=True).fgetxattr
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        function.restype = ctypes.c_ssize_t
        output = ctypes.create_string_buffer(100)
        with path.open("rb") as stream:
            size = function(stream.fileno(), self.name, output, 100, 0, 0)
        assert size >= 0
        return output.raw[:size]


def main(exchange_race=False):
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="selene-recovery-probe-") as directory:
        root = Path(directory)
        path = root / "first.py"
        original = b"value = 1\r\n"
        path.write_bytes(original)
        canary = MetadataCanary()
        canary.set(path)
        metadata = canary.read(path)
        config = SeleneConfig().with_headless_mode_overrides()
        config.persist_symbol_cache = False
        project = Project(
            project_root=str(root), project_config=ProjectConfig(project_name="recovery-probe", language_servers=[LanguageServerId.PYTHON]),
            selene_config=config,
        )
        try:
            service = RecoverableChanges(project)
            plan = service.prepare("probe", changes=(ProposedFileChange("first.py", hashlib.sha256(original).hexdigest(), "value = 2\n"),))
            applied = service.run(plan.plan_id)
            assert applied.status == ("conflict" if exchange_race else "applied"), applied
            assert path.read_bytes() == b"value = 2\n"
            assert canary.read(path) == metadata
            rolled_back = service.run(plan.plan_id, action="rollback")
            assert rolled_back.status == "rolled_back", rolled_back
            assert path.read_bytes() == (b"concurrent_edit = 99\n" if exchange_race else original)
            assert canary.read(path) == metadata
            kept = [p.read_bytes() for p in (root / plan.recovery_directory).iterdir() if p.is_file()]
            assert original in kept and b"value = 2\n" in kept

            # remove write permission after the first file to exercise a real second-directory failure
            second = root / "nested"
            second.mkdir()
            (second / "second.py").write_text("second = 1\n")
            class RestrictSecondDirectory:
                def after_file(self, changed_path, direction):
                    if changed_path == "first.py" and direction == "apply":
                        second.chmod(0o555)
            service = RecoverableChanges(project, observer=RestrictSecondDirectory())
            failure_plan = service.prepare("permissions", changes=tuple(
                ProposedFileChange(p, hashlib.sha256((root / p).read_bytes()).hexdigest(), "next_value = 3\n")
                for p in ("first.py", "nested/second.py")
            ))
            try:
                partial = service.run(failure_plan.plan_id)
                assert [f.status for f in partial.files] == ["applied", "failed"], partial
                assert (second / "second.py").read_text() == "second = 1\n"
            finally:
                second.chmod(0o755)
            assert RecoverableChanges(project).run(failure_plan.plan_id, action="rollback").status == "rolled_back"
            import selene.edit_plans.service
            code_root = Path(selene.edit_plans.service.__file__).resolve().parents[3]
            sources = list((code_root / "src/selene/edit_plans").glob("*.py"))
            return {
                "platform": platform.platform(), "synthetic_only": True, "model_calls": 0,
                "native_exchange_race_injected": exchange_race,
                "competing_content_preserved_and_restored": exchange_race,
                "extended_attribute_preserved": True,
                "second_directory_permission_failure_is_partial_and_recoverable": True,
                "original_and_proposed_snapshots_preserved": True,
                "source_sha256": {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            }
        finally:
            project.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-race", action="store_true")
    args = parser.parse_args()
    print(json.dumps(main(args.exchange_race), indent=2))
