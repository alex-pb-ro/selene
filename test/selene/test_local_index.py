import json
import os
import sys
from concurrent.futures import CancelledError
from pathlib import Path
from unittest.mock import MagicMock

import pathspec
import pytest

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.indexing.journal import ChangeJournal
from selene.indexing.local_index import LocalSourceIndex
from selene.indexing.scope import ProjectSourceScope, SourceRootReplaced, SourceScopeError
from selene.project import Project
from selene.tools import SearchIndexTool
from selene.util.cancellation import CancellationToken
from solidlsp.ls_config import LanguageServerId


class InclusionPolicy:
    def __init__(self, root):
        self.root = root
        self.patterns = []
        self.spec = pathspec.PathSpec.from_lines("gitwildmatch", [])

    def includes(self, relative_path, *, directory):
        if relative_path in {"", "."}:
            return True
        if any(part in {".git", ".selene"} for part in Path(relative_path).parts):
            return False
        return not self.spec.match_file(relative_path + ("/" if directory else ""))

    def is_source(self, relative_path):
        return relative_path.endswith(".py")

    def signature(self):
        return repr(self.patterns)

    def refresh(self):
        ignore = self.root / ".gitignore"
        self.patterns = ignore.read_text().splitlines() if ignore.exists() else []
        self.spec = pathspec.PathSpec.from_lines("gitwildmatch", self.patterns)


class ExplicitJournal(ChangeJournal):
    def read(self):
        return self._snapshot()

    def rebuild(self):
        pass

    def close(self):
        pass


@pytest.fixture
def index(tmp_path):
    index = LocalSourceIndex(ProjectSourceScope(tmp_path), InclusionPolicy(tmp_path))
    yield index
    index.close()


def test_index_search_returns_current_code_docs_hashes_and_lines(index, tmp_path):
    (tmp_path / "payment.py").write_text("def capturePayment():\n    return 'approved'\n")
    (tmp_path / "README.md").write_text("Payment capture follows company approval.\n")
    results = index.search("payment capture")
    assert {match.path for match in results.matches} == {"payment.py", "README.md"}
    assert results.matches[0].lines[0][0] == 1
    assert all(len(match.sha256) == 64 for match in results.matches)
    (tmp_path / "payment.py").write_text("def refundPayment():\n    return 'refunded'\n")
    assert [match.path for match in index.search("refunded").matches] == ["payment.py"]
    assert [match.path for match in index.search("approved").matches] == []


@pytest.mark.parametrize("replace_file", [False, True])
@pytest.mark.parametrize("mtime_delta", [0, -1000000000])
def test_index_observes_immediate_preserved_timestamp_edits(index, tmp_path, replace_file, mtime_delta):
    path = tmp_path / "module.py"
    path.write_text("value = 'alpha'\n")
    before = index.refresh()
    stamp = path.stat()
    if replace_file:
        staged = tmp_path / "staged"
        staged.write_text("value = 'bravo'\n")
        os.replace(staged, path)
    else:
        path.write_text("value = 'bravo'\n")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + mtime_delta))
    after = index.refresh()
    assert before.files["module.py"].sha256 != after.files["module.py"].sha256
    assert after.status.generation > before.status.generation
    assert index.search("bravo").matches[0].path == "module.py"


def test_index_tracks_create_rename_delete_and_new_subtrees(index, tmp_path):
    index.refresh()
    (tmp_path / "new").mkdir()
    path = tmp_path / "new" / "module.py"
    path.write_text("created_symbol = 1\n")
    assert index.search("created_symbol").matches[0].path == "new/module.py"
    moved = tmp_path / "moved.py"
    path.rename(moved)
    assert index.search("created_symbol").matches[0].path == "moved.py"
    moved.unlink()
    assert not index.search("created_symbol").matches


def test_index_refreshes_ignore_rules_without_reactivation(index, tmp_path):
    (tmp_path / "public.py").write_text("company_symbol = 1\n")
    (tmp_path / "private.py").write_text("company_symbol = 2\n")
    assert len(index.search("company_symbol").matches) == 2
    (tmp_path / ".gitignore").write_text("private.py\n")
    assert [match.path for match in index.search("company_symbol").matches] == ["public.py"]
    (tmp_path / ".gitignore").write_text("")
    assert len(index.search("company_symbol").matches) == 2


def test_scope_excludes_escaping_and_ignored_aliases_and_breaks_cycles(index, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-external.py")
    outside.write_text("external_private_symbol = 1\n")
    (tmp_path / "escape.py").symlink_to(outside)
    (tmp_path / "cycle").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "private.py").write_text("ignored_private_symbol = 1\n")
    (tmp_path / "alias.py").symlink_to(tmp_path / "ignored" / "private.py")
    (tmp_path / ".gitignore").write_text("ignored/\n")
    result = index.search("private_symbol")
    assert not result.matches
    assert {issue.reason for issue in result.status.issues} == {"directory_symlink_cycle", "outside_project"}
    with pytest.raises(SourceScopeError):
        index.scope.read("escape.py")


def test_root_replacement_requires_reactivation(index, tmp_path):
    (tmp_path / "old.py").write_text("old_source = 1\n")
    index.refresh()
    moved = tmp_path.with_name(tmp_path.name + "-moved")
    tmp_path.rename(moved)
    tmp_path.mkdir()
    (tmp_path / "new.py").write_text("new_source = 1\n")
    try:
        with pytest.raises(SourceRootReplaced):
            index.refresh()
    finally:
        (tmp_path / "new.py").unlink()
        tmp_path.rmdir()
        moved.rename(tmp_path)


def test_new_in_project_alias_tracks_later_target_changes(index, tmp_path):
    path = tmp_path / "module.py"
    path.write_text("before = 1\n")
    index.refresh()
    (tmp_path / "alias.py").symlink_to(path)
    assert {match.path for match in index.search("before").matches} == {"module.py", "alias.py"}
    path.write_text("after = 1\n")
    assert {match.path for match in index.search("after").matches} == {"module.py", "alias.py"}


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Requires a supported native watcher")
def test_ignored_external_directory_alias_does_not_force_reconciliation(index, tmp_path):
    (tmp_path / "cache").symlink_to(tmp_path.parent, target_is_directory=True)
    (tmp_path / ".gitignore").write_text("cache/\n")
    path = tmp_path / "module.py"
    path.write_text("before = 1\n")
    index.refresh()
    path.write_text("after = 1\n")
    result = index.search("after")
    assert [match.path for match in result.matches] == ["module.py"]
    assert result.status.reconciliation_reasons == ()


def test_cancelled_observation_retains_explicit_changes(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("before = 1\n")
    journal = ExplicitJournal(tmp_path)
    index = LocalSourceIndex(ProjectSourceScope(tmp_path), InclusionPolicy(tmp_path), journal=journal)
    try:
        index.refresh()
        path.write_text("after = 1\n")
        index.record_local_write("module.py")
        token = CancellationToken()
        token.cancel()
        with token.bind(), pytest.raises(CancelledError):
            index.refresh()
        assert index.search("after").matches[0].path == "module.py"
    finally:
        index.close()


def test_overflow_reconciles_files_missing_from_the_event_batch(tmp_path):
    journal = ExplicitJournal(tmp_path, pending_limit=1)
    index = LocalSourceIndex(ProjectSourceScope(tmp_path), InclusionPolicy(tmp_path), journal=journal)
    try:
        index.refresh()
        for name in ("first.py", "second.py", "third.py"):
            (tmp_path / name).write_text("new_symbol = 1\n")
            journal.record_local_write(name)
        result = index.search("new_symbol")
        assert len(result.matches) == 3
        assert "event_buffer_overflow" in result.status.reconciliation_reasons
    finally:
        index.close()


def test_acknowledgement_preserves_newer_changes_to_the_same_path(tmp_path):
    journal = ExplicitJournal(tmp_path)
    journal.record_local_write("module.py")
    first = journal.read()
    journal.record_local_write("module.py")
    journal.acknowledge(first.cursor)
    assert journal.read().paths == {"module.py"}


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Requires a supported native watcher")
def test_unchanged_native_observation_performs_no_file_reads_or_directory_enumerations(index, tmp_path):
    for number in range(30):
        (tmp_path / f"module_{number}.py").write_text(f"value_{number} = {number}\n")
    observation = index.refresh()
    assert observation.status.watcher != "reconciliation"
    events = []
    active = [True]

    def audit(event, args):
        if active[0] and event in {"open", "os.scandir", "os.listdir"}:
            events.append(event)

    sys.addaudithook(audit)
    try:
        unchanged = index.refresh()
    finally:
        active[0] = False
    assert events == []
    assert unchanged.status.generation == observation.status.generation


def test_reconciliation_mode_reads_current_content_and_reports_coverage(tmp_path):
    index = LocalSourceIndex(ProjectSourceScope(tmp_path), InclusionPolicy(tmp_path), native_watch=False)
    try:
        (tmp_path / "module.py").write_text("first_symbol = 1\n")
        assert index.search("first_symbol").status.watcher == "reconciliation"
        (tmp_path / "module.py").write_text("second_symbol = 1\n")
        assert index.search("second_symbol").matches[0].path == "module.py"
    finally:
        index.close()


def test_project_search_tool_observes_local_excludes_and_configuration_changes(tmp_path):
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="index", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )
    agent = MagicMock()
    agent.get_active_project_or_raise.return_value = project
    agent.selene_config.default_max_tool_answer_chars = 100000
    tool = SearchIndexTool(agent)
    (tmp_path / "public.py").write_text("company_symbol = 1\n")
    (tmp_path / "private.py").write_text("company_symbol = 2\n")
    try:
        assert len(json.loads(tool.apply("company_symbol"))["matches"]) == 2
        (tmp_path / ".git" / "info").mkdir(parents=True)
        (tmp_path / ".git" / "info" / "exclude").write_text("private.py\n")
        assert [match["path"] for match in json.loads(tool.apply("company_symbol"))["matches"]] == ["public.py"]
        project.project_config.ignored_paths.append("public.py")
        assert json.loads(tool.apply("company_symbol"))["matches"] == []
        project.project_config.ignored_paths.clear()
        (tmp_path / ".git" / "info" / "exclude").write_text("")
        assert len(json.loads(tool.apply("company_symbol"))["matches"]) == 2
    finally:
        project.shutdown()


def test_search_line_numbers_follow_source_newlines(index, tmp_path):
    (tmp_path / "module.py").write_bytes(b"value = 1\n# form\x0cfeed target\n# next\n")
    assert index.search("target").matches[0].lines == ((2, "# form\x0cfeed target"),)


def test_periodic_reconciliation_recovers_an_unreported_change(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("before = 1\n")
    journal = ExplicitJournal(tmp_path)
    index = LocalSourceIndex(ProjectSourceScope(tmp_path), InclusionPolicy(tmp_path), journal=journal, reconcile_interval=0.000001)
    try:
        index.refresh()
        path.write_text("after = 1\n")
        assert index.search("after").matches[0].path == "module.py"
    finally:
        index.close()


def test_cancelled_mid_read_does_not_acknowledge_uncommitted_changes(tmp_path):
    class CancelDuringRead(ProjectSourceScope):
        cancellation = None

        def read(self, relative_path, *, max_bytes=None):
            result = super().read(relative_path, max_bytes=max_bytes)
            if self.cancellation is not None:
                self.cancellation.cancel()
            return result

    scope = CancelDuringRead(tmp_path)
    journal = ExplicitJournal(tmp_path)
    index = LocalSourceIndex(scope, InclusionPolicy(tmp_path), journal=journal)
    path = tmp_path / "module.py"
    path.write_text("before = 1\n")
    try:
        index.refresh()
        path.write_text("after = 1\n")
        index.record_local_write("module.py")
        scope.cancellation = CancellationToken()
        with scope.cancellation.bind(), pytest.raises(CancelledError):
            index.refresh()
        scope.cancellation = None
        assert index.search("after").matches[0].path == "module.py"
    finally:
        index.close()


def test_unreadable_ignore_file_blocks_search_until_it_is_fixed(tmp_path):
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="index", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )
    (tmp_path / "private.py").write_text("sensitivecanary = 1\n")
    (tmp_path / ".gitignore").write_text("private.py\n")
    try:
        index = project.get_local_index()
        assert not index.search("sensitivecanary").matches
        (tmp_path / ".gitignore").write_bytes(b"\xff")
        with pytest.raises(ValueError, match="ignore spec"):
            index.search("sensitivecanary")
        (tmp_path / ".gitignore").write_text("")
        assert index.search("sensitivecanary").matches[0].path == "private.py"
    finally:
        project.shutdown()
