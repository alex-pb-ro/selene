import difflib
import hashlib
import os

import pytest

from selene.changes.model import ChangeConflict, ChangeInputError, ProposedFileChange
from selene.changes.resolver import ChangeResolver
from selene.changes.unified_diff import UnifiedDiff
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.context.model import StaleContextError
from selene.context.sources import ContextSources
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


@pytest.mark.parametrize(
    "before,after",
    [
        ("one\ntwo\nthree\n", "one\nsecond\nthree\n"),
        ("alpha\n", "before\nalpha\nafter\n"),
        ("hello\r\nworld\r\n", "hello\r\n😀\r\n"),
    ],
)
def test_diff_application_preserves_exact_content_and_reports_conflicts(before, after):
    diff = "".join(
        difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="a/code.py", tofile="b/code.py")
    )
    (patch,) = UnifiedDiff.parse(diff)
    assert patch.path == "code.py"
    assert patch.apply(before) == after
    with pytest.raises(ChangeConflict):
        patch.apply("different\n" + before)


def test_diff_supports_creation_deletion_and_no_final_newline():
    created, deleted = UnifiedDiff.parse(
        "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+added\n\\ No newline at end of file\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-removed\n\\ No newline at end of file\n"
    )
    assert created.apply(None) == "added"
    assert deleted.apply("removed") is None


@pytest.mark.parametrize(
    "diff",
    [
        "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1 @@\n-a\n+b\n",
        "--- a/x.py\n+++ b/x.py\n@@ -1 +9 @@\n-a\n+b\n",
        "--- a/x.py\n+++ b/other.py\n@@ -1 +1 @@\n-a\n+b\n",
        "diff --git a/x.py b/x.py\nGIT binary patch\nabc\n",
    ],
)
def test_unsupported_or_inconsistent_diff_fails_explicitly(diff):
    with pytest.raises((ChangeInputError, ChangeConflict)):
        for patch in UnifiedDiff.parse(diff):
            patch.apply("a\n")


@pytest.fixture
def project(tmp_path):
    (tmp_path / "code.py").write_text("def public(value):\n    return value\n")
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="change-inputs", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )
    yield project
    project.shutdown()


def resolver(project):
    index = project.get_local_index()
    return ChangeResolver(project, ContextSources(index, index.refresh(), project.project_config.encoding))


def test_proposals_materialize_versions_and_ranges_without_changing_files(project, tmp_path):
    path = tmp_path / "code.py"
    before = path.read_bytes()
    proposed = "def public(value, extra):\n    return value + extra\n"
    changes = resolver(project).resolve(
        changes=(
            ProposedFileChange("code.py", hashlib.sha256(before).hexdigest(), proposed),
            ProposedFileChange("new.py", None, "created = True\n"),
        )
    )
    assert changes[0].old_content == before.decode()
    assert changes[0].new_content == proposed
    assert changes[0].proposed_sha256 == hashlib.sha256(proposed.encode()).hexdigest()
    assert changes[0].ranges[0].old_start == 0
    assert changes[0].ranges[0].old_end == 2
    assert changes[1].kind == "create"
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["code.py"]


def test_proposals_reject_wrong_hashes_and_later_restored_timestamp_edits(project, tmp_path):
    reader = resolver(project)
    source = tmp_path / "code.py"
    with pytest.raises(ChangeConflict):
        reader.resolve(changes=(ProposedFileChange("code.py", "wrong", "changed\n"),))
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    changes = reader.resolve(changes=(ProposedFileChange("code.py", sha256, "changed\n"),))
    stamp = source.stat()
    source.write_text(source.read_text().replace("value", "other"))
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises((ChangeConflict, StaleContextError)):
        reader.validate(changes)


def test_proposals_reject_excluded_external_and_duplicate_alias_paths(project, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    (tmp_path / "alias.py").symlink_to(tmp_path / "code.py")
    (tmp_path / ".gitignore").write_text("private/\n")
    for path in ("private/secret.py", "escape/new.py", ".selene/secret.py"):
        with pytest.raises(ChangeInputError):
            resolver(project).resolve(changes=(ProposedFileChange(path, None, "new\n"),))
    sha256 = hashlib.sha256((tmp_path / "code.py").read_bytes()).hexdigest()
    with pytest.raises(ChangeInputError, match="canonical"):
        resolver(project).resolve(changes=tuple(ProposedFileChange(path, sha256, "new\n") for path in ("code.py", "alias.py")))


def test_diff_is_bound_to_current_source_and_does_not_overwrite_unrelated_content(project, tmp_path):
    source = tmp_path / "code.py"
    before = source.read_text()
    (tmp_path / "unrelated.txt").write_text("uncommitted user content\n")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            before.replace("public(value)", "public(value, extra)").splitlines(keepends=True),
            fromfile="a/code.py",
            tofile="b/code.py",
        )
    )
    changes = resolver(project).resolve(diff=diff)
    assert changes[0].expected_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.read_text() == before
    assert (tmp_path / "unrelated.txt").read_text() == "uncommitted user content\n"
