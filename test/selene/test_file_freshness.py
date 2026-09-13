import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.file_change_notifier import LanguageServerFileChangeNotifier
from selene.project import Project
from selene.util.file_snapshot import FileSnapshotConflict, FileSnapshotReader
from solidlsp.ls import LSPFileBuffer
from solidlsp.ls_config import LanguageServerId
from solidlsp.lsp_protocol_handler.lsp_types import FileChangeType


class RecordingServer:
    def __init__(self):
        self.server = SimpleNamespace(notify=self)
        self.messages = []
        self.opened = []
        self.document_changes = []
        self.fail_next = False
        self.entered: Event | None = None
        self.release: Event | None = None

    def did_change_watched_files(self, params):
        self.messages.append(params)
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(3)
            self.entered = None
        if self.fail_next:
            self.fail_next = False
            raise OSError("Delivery outcome unknown")

    def did_open_text_document(self, params):
        self.opened.append(params)

    def did_change_text_document(self, params):
        self.document_changes.append(params)
        if self.fail_next:
            self.fail_next = False
            raise OSError("Delivery outcome unknown")

    def did_close_text_document(self, params):
        pass

    def is_ignored_path(self, path, ignore_unsupported_files=True):
        return False

    @contextmanager
    def open_file(self, path):
        yield


class RecordingManager:
    def __init__(self, *servers):
        self.servers = list(servers)

    def iter_language_servers(self):
        return iter(self.servers)


@pytest.fixture
def project(tmp_path):
    return Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="freshness", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )


def rewrite(path, content, mtime_delta, replace=False):
    before = path.stat()
    if replace:
        staged = path.with_suffix(".stage")
        staged.write_text(content)
        os.replace(staged, path)
    else:
        path.write_text(content)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + mtime_delta))


@pytest.mark.parametrize("mtime_delta", [0, -1_000_000_000])
@pytest.mark.parametrize("replace", [False, True])
def test_source_notifications_detect_same_size_edits_with_restored_or_older_times(project, tmp_path, mtime_delta, replace):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    server = RecordingServer()
    notifier = LanguageServerFileChangeNotifier(project, RecordingManager(server))
    rewrite(path, "value = 2\n", mtime_delta, replace)
    assert notifier.poll_and_notify() == 1
    assert server.messages[-1]["changes"] == [{"uri": path.as_uri(), "type": FileChangeType.Changed}]
    assert notifier.poll_and_notify() == 0


def test_failed_notification_is_retried_even_after_contents_revert(project, tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    first, second = RecordingServer(), RecordingServer()
    notifier = LanguageServerFileChangeNotifier(project, RecordingManager(first, second))
    second.fail_next = True
    rewrite(path, "value = 2\n", 0)
    with pytest.raises(OSError, match="unknown"):
        notifier.poll_and_notify()
    rewrite(path, "value = 1\n", 0)
    assert notifier.poll_and_notify() == 1
    for server in (first, second):
        assert len(server.messages) == 2
        assert server.messages[-1]["changes"] == [{"uri": path.as_uri(), "type": FileChangeType.Changed}]
    assert notifier.poll_and_notify() == 0


def test_created_file_with_uncertain_delivery_is_deleted_on_retry(project, tmp_path):
    server = RecordingServer()
    notifier = LanguageServerFileChangeNotifier(project, RecordingManager(server))
    path = tmp_path / "new.py"
    path.write_text("value = 1\n")
    server.fail_next = True
    with pytest.raises(OSError):
        notifier.poll_and_notify()
    path.unlink()
    assert notifier.poll_and_notify() == 1
    assert server.messages[-1]["changes"] == [{"uri": path.as_uri(), "type": FileChangeType.Deleted}]


@pytest.mark.skipif(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, reason="Requires POSIX file permissions as non-root")
def test_unreadable_file_does_not_become_a_deletion(project, tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    server = RecordingServer()
    notifier = LanguageServerFileChangeNotifier(project, RecordingManager(server))
    rewrite(path, "value = 2\n", 0)
    mode = path.stat().st_mode
    path.chmod(0)
    try:
        with pytest.raises(PermissionError):
            notifier.poll_and_notify()
    finally:
        path.chmod(mode)
    assert notifier.poll_and_notify() == 1
    assert server.messages == [{"changes": [{"uri": path.as_uri(), "type": FileChangeType.Changed}]}]


def test_concurrent_observations_wait_for_prior_delivery(project, tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    server = RecordingServer()
    entered, release = Event(), Event()
    server.entered, server.release = entered, release
    notifier = LanguageServerFileChangeNotifier(project, RecordingManager(server))
    with ThreadPoolExecutor(max_workers=2) as pool:
        rewrite(path, "value = 2\n", 0)
        first = pool.submit(notifier.poll_and_notify)
        try:
            assert entered.wait(1)
            rewrite(path, "value = 3\n", 0)
            second = pool.submit(notifier.poll_and_notify)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.03)
        finally:
            release.set()
        assert first.result(timeout=1) == 1
        assert second.result(timeout=1) == 1
    assert len(server.messages) == 2
    assert notifier.poll_and_notify() == 0


def make_buffer(path, server, open_in_ls=True):
    return LSPFileBuffer(path, path.as_uri(), "utf-8", 1, "python", 1, server, open_in_ls=open_in_ls)


@pytest.mark.parametrize("mtime_delta", [0, -1_000_000_000])
def test_open_buffer_refreshes_contents_hash_and_server_with_non_increasing_times(tmp_path, mtime_delta):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    server = RecordingServer()
    buffer = make_buffer(path, server)
    previous_hash = buffer.content_hash
    rewrite(path, "value = 2\n", mtime_delta)
    assert buffer.contents == "value = 2\n"
    assert buffer.content_hash != previous_hash
    buffer.ensure_open_in_ls()
    assert server.document_changes[-1]["contentChanges"] == [{"text": "value = 2\n"}]
    assert server.document_changes[-1]["textDocument"]["version"] > server.opened[0]["textDocument"]["version"]


def test_buffer_keeps_draft_until_disk_conflict_is_resolved(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    buffer = make_buffer(path, RecordingServer())
    buffer.contents = "value = 2\n"
    buffer.ensure_open_in_ls()
    assert buffer.contents == "value = 2\n"
    rewrite(path, "value = 3\n", 0)
    with pytest.raises(FileSnapshotConflict, match="unsaved"):
        buffer.ensure_open_in_ls()
    rewrite(path, "value = 1\n", 0)
    assert buffer.contents == "value = 2\n"
    path.write_text(buffer.contents)
    buffer.ensure_open_in_ls()
    rewrite(path, "value = 4\n", 0)
    assert buffer.contents == "value = 4\n"


def test_buffer_noop_edits_do_not_create_false_conflicts(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    buffer = make_buffer(path, RecordingServer(), open_in_ls=False)
    buffer.contents = "value = 2\n"
    buffer.contents = "value = 1\n"
    rewrite(path, "value = 3\n", 0)
    assert buffer.contents == "value = 3\n"


def test_buffer_retries_failed_change_notification(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    server = RecordingServer()
    buffer = make_buffer(path, server)
    rewrite(path, "value = 2\n", 0)
    server.fail_next = True
    with pytest.raises(OSError):
        buffer.ensure_open_in_ls()
    buffer.ensure_open_in_ls()
    assert len(server.document_changes) == 2
    assert server.document_changes[-1]["contentChanges"] == [{"text": "value = 2\n"}]
    assert server.document_changes[-1]["textDocument"]["version"] > server.document_changes[0]["textDocument"]["version"]


def test_file_snapshot_describes_the_returned_bytes(tmp_path):
    path = tmp_path / "module.py"
    path.write_bytes(b"value = 1\r\n")
    snapshot = FileSnapshotReader.read(path)
    assert snapshot.content == path.read_bytes()
    assert snapshot.sha256 == hashlib.sha256(snapshot.content).hexdigest()
    assert FileSnapshotReader.fingerprint(path) == snapshot.sha256
    rewrite(path, "value = 2\n", 0, replace=True)
    assert FileSnapshotReader.fingerprint(path) != snapshot.sha256


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO fixture")
def test_file_snapshot_rejects_a_pipe_without_waiting_for_a_writer(tmp_path):
    path = tmp_path / "pipe.py"
    os.mkfifo(path)
    with pytest.raises(OSError, match="regular source file"):
        FileSnapshotReader.fingerprint(path)
