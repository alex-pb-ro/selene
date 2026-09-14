"""Synthetic index acceptance probe, launched with -I -S inside the isolated image."""

import runpy
import site
import sys

runpy.run_path("/opt/selene/src/selene/isolation/linux_network.py")["LinuxNetworkBoundary"].enter()
site.main()
sys.path.insert(0, "/opt/selene/src")

import hashlib
import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


def main():
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="selene-linux-index-") as directory:
        root = Path(directory)
        path = root / "module.py"
        path.write_text("value = 'alpha'\n")
        config = SeleneConfig().with_headless_mode_overrides()
        config.persist_symbol_cache = False
        project = Project(
            project_root=str(root), project_config=ProjectConfig(project_name="linux-index", language_servers=[LanguageServerId.PYTHON]),
            selene_config=config,
        )
        try:
            index = project.get_local_index()
            before = index.refresh()
            assert before.status.watcher == "InotifyJournal"
            stamp = path.stat()
            path.write_text("value = 'bravo'\n")
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            assert index.search("bravo").matches[0].path == "module.py"
            new_directory = root / "new"
            new_directory.mkdir()
            (new_directory / "new.py").write_text("newcanary = 1\n")
            assert index.search("newcanary").matches[0].path == "new/new.py"
            (new_directory / "new.py").rename(root / "moved.py")
            assert index.search("newcanary").matches[0].path == "moved.py"
            (root / ".gitignore").write_text("moved.py\n")
            assert not index.search("newcanary").matches
            (root / ".gitignore").write_text("")
            assert index.search("newcanary").matches[0].path == "moved.py"
            (root / "moved.py").unlink()
            assert not index.search("newcanary").matches
            queue_limit = int(Path("/proc/sys/fs/inotify/max_queued_events").read_text())
            if queue_limit > 20000:
                raise RuntimeError("Queue limit exceeds the bounded kernel-overflow probe workload")
            number_of_files = queue_limit // 2 + 20
            for number in range(number_of_files):
                (root / f"overflow_{number}.py").write_text(f"overflowcanary = {number}\n")
            recovered = index.refresh()
            assert "kernel_event_overflow" in recovered.status.reconciliation_reasons
            assert len(recovered.source_fingerprints) == number_of_files + 1
            assert index.search("overflowcanary", limit=3).matches
            result = {
                "platform": platform.platform(), "watcher": recovered.status.watcher,
                "same_size_preserved_mtime": True, "create_rename_delete": True, "ignore_reload": True,
                "real_kernel_overflow_recovered": True, "kernel_queue_limit": queue_limit,
                "recovered_source_files": len(recovered.source_fingerprints),
                "network_filter_active": "Seccomp:\t2" in Path("/proc/self/status").read_text(),
                "source_sha256": {
                    str(path.relative_to("/opt/selene")): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in Path("/opt/selene/src/selene/indexing").glob("*.py")
                },
            }
            print(json.dumps(result, indent=2))
        finally:
            project.shutdown()


if __name__ == "__main__":
    main()
