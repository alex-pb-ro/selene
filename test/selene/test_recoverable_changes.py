import hashlib
import os
import shutil
import subprocess
import sys
from concurrent.futures import CancelledError
from pathlib import Path

import pytest

from selene.changes.model import ChangeConflict, ChangeInputError, ProposedFileChange
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.edit_plans.service import RecoverableChanges
from selene.project import Project
from selene.util.cancellation import CancellationToken
from solidlsp.ls_config import LanguageServerId

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Requires a supported atomic file-exchange platform")


def make_project(root: Path) -> Project:
    return Project(
        project_root=str(root),
        project_config=ProjectConfig(project_name="recoverable-changes", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )


@pytest.fixture
def project(tmp_path):
    (tmp_path / "first.py").write_bytes(b"value = 1\r\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "second.py").write_text("second = 1\n")
    project = make_project(tmp_path)
    yield project
    project.shutdown()


def proposal(root: Path, path: str, text: str | None) -> ProposedFileChange:
    source = root / path
    return ProposedFileChange(path, hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None, text)


def test_plan_preserves_bytes_modes_and_unrelated_edits_with_idempotent_apply_and_rollback(project, tmp_path):
    original = (tmp_path / "first.py").read_bytes()
    os.chmod(tmp_path / "first.py", 0o750)
    (tmp_path / "unrelated.txt").write_text("uncommitted user content\n")
    changes = (
        proposal(tmp_path, "first.py", 'value = "😀 café"\r\n'),
        proposal(tmp_path, "nested/second.py", None),
        proposal(tmp_path, "new.py", "created = True\n"),
    )
    service = RecoverableChanges(project)
    plan = service.prepare("byte-preservation", changes=changes)
    assert plan.status == "prepared"
    assert (tmp_path / "first.py").read_bytes() == original
    assert service.prepare("byte-preservation", changes=changes).plan_id == plan.plan_id
    assert service.run(plan.plan_id).status == "applied"
    assert (tmp_path / "first.py").read_bytes() == 'value = "😀 café"\r\n'.encode()
    assert (tmp_path / "first.py").stat().st_mode & 0o777 == 0o750
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.py")) == ["first.py", "new.py"]
    applied_inode = (tmp_path / "first.py").stat().st_ino
    assert service.run(plan.plan_id).status == "applied"
    assert (tmp_path / "first.py").stat().st_ino == applied_inode
    assert service.prepare("byte-preservation", changes=changes).status == "applied"
    assert service.run(plan.plan_id, action="rollback").status == "rolled_back"
    assert service.run(plan.plan_id, action="rollback").status == "rolled_back"
    assert (tmp_path / "first.py").read_bytes() == original
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.py")) == ["first.py", "nested/second.py"]
    assert (tmp_path / "unrelated.txt").read_text() == "uncommitted user content\n"
    with pytest.raises(ChangeConflict, match="different"):
        service.prepare("byte-preservation", changes=(proposal(tmp_path, "first.py", "value = 3\n"),))


def test_stale_second_file_prevents_all_writes_even_with_preserved_timestamp(project, tmp_path):
    changes = tuple(proposal(tmp_path, path, "value = 2\n") for path in ("first.py", "nested/second.py"))
    service = RecoverableChanges(project)
    plan = service.prepare("stale", changes=changes)
    second = tmp_path / "nested" / "second.py"
    metadata = second.stat()
    second.write_text("concurrent = 99\n")
    os.utime(second, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    result = service.run(plan.plan_id)
    assert [item.status for item in result.files] == ["pending", "conflict"]
    assert (tmp_path / "first.py").read_bytes() == b"value = 1\r\n"
    assert second.read_text() == "concurrent = 99\n"


def test_second_directory_permission_failure_reports_partial_and_can_roll_back(project, tmp_path):
    class RestrictSecondDirectory:
        def after_file(self, path, direction):
            if path == "first.py" and direction == "apply":
                os.chmod(tmp_path / "nested", 0o555)

    changes = tuple(proposal(tmp_path, path, "value = 2\n") for path in ("first.py", "nested/second.py"))
    service = RecoverableChanges(project, observer=RestrictSecondDirectory())
    plan = service.prepare("permissions", changes=changes)
    try:
        result = service.run(plan.plan_id)
        assert [item.status for item in result.files] == ["applied", "failed"]
        assert result.status == "partial"
        assert (tmp_path / "first.py").read_text() == "value = 2\n"
        assert (tmp_path / "nested" / "second.py").read_text() == "second = 1\n"
    finally:
        os.chmod(tmp_path / "nested", 0o755)
    assert RecoverableChanges(project).run(plan.plan_id, action="rollback").status == "rolled_back"
    assert (tmp_path / "first.py").read_bytes() == b"value = 1\r\n"


def test_cancellation_between_files_is_recoverable_without_reapplying_the_first(project, tmp_path):
    token = CancellationToken()

    class CancelAfterFile:
        def after_file(self, path, direction):
            token.cancel()

    service = RecoverableChanges(project, observer=CancelAfterFile())
    plan = service.prepare("cancel", changes=tuple(proposal(tmp_path, p, "value = 2\n") for p in ("first.py", "nested/second.py")))
    with token.bind(), pytest.raises(CancelledError):
        service.run(plan.plan_id)
    first_inode = (tmp_path / "first.py").stat().st_ino
    result = RecoverableChanges(project).run(plan.plan_id)
    assert result.status == "applied"
    assert (tmp_path / "first.py").stat().st_ino == first_inode
    assert (tmp_path / "nested" / "second.py").read_text() == "value = 2\n"


def test_rollback_preserves_later_external_edit_and_retains_original(project, tmp_path):
    service = RecoverableChanges(project)
    plan = service.prepare("external-after-apply", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    assert service.run(plan.plan_id).status == "applied"
    (tmp_path / "first.py").write_text("external = 3\n")
    result = service.run(plan.plan_id, action="rollback")
    assert result.status == "conflict"
    assert (tmp_path / "first.py").read_text() == "external = 3\n"
    retained = tmp_path / result.recovery_directory
    assert b"value = 1\r\n" in [path.read_bytes() for path in retained.iterdir() if path.is_file()]


def test_writer_with_open_original_descriptor_is_preserved_and_reported(project, tmp_path):
    service = RecoverableChanges(project)
    plan = service.prepare("open-fd", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    with (tmp_path / "first.py").open("r+b") as writer:
        assert service.run(plan.plan_id).status == "applied"
        writer.seek(0)
        writer.write(b"external = 7\n")
        writer.truncate()
        writer.flush()
        assert service.run(plan.plan_id, action="inspect").status == "conflict"
        result = service.run(plan.plan_id, action="rollback")
    assert result.status == "rolled_back"
    assert (tmp_path / "first.py").read_bytes() == b"external = 7\n"


def test_syntax_errors_are_reviewable_and_require_explicit_override(project, tmp_path):
    service = RecoverableChanges(project)
    changes = (proposal(tmp_path, "first.py", "def broken(\n"),)
    plan = service.prepare("syntax", changes=changes)
    assert plan.diagnostics[0].status == "error"
    with pytest.raises(ChangeInputError, match="syntax"):
        service.run(plan.plan_id)
    assert (tmp_path / "first.py").read_bytes() == b"value = 1\r\n"
    overridden = service.prepare("syntax-override", changes=changes, allow_syntax_errors=True)
    assert service.run(overridden.plan_id).status == "applied"


def test_copied_plan_cannot_be_replayed_in_another_project(project, tmp_path):
    service = RecoverableChanges(project)
    plan = service.prepare("project-scope", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    destination = tmp_path.parent / (tmp_path.name + "-copy")
    shutil.copytree(tmp_path, destination)
    other = make_project(destination)
    try:
        with pytest.raises(ChangeConflict, match="different project"):
            RecoverableChanges(other).run(plan.plan_id)
        assert (destination / "first.py").read_bytes() == b"value = 1\r\n"
    finally:
        other.shutdown()


def test_symlinked_parent_and_replaced_parent_do_not_write_outside_the_prepared_scope(project, tmp_path):
    service = RecoverableChanges(project)
    plan = service.prepare("parent-identity", changes=(proposal(tmp_path, "nested/second.py", "value = 2\n"),))
    original = tmp_path / "nested"
    moved = tmp_path / "preserved"
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    result = service.run(plan.plan_id)
    assert result.status == "conflict"
    assert (moved / "second.py").read_text() == "second = 1\n"


@pytest.mark.parametrize("direction", ["apply", "rollback"])
@pytest.mark.parametrize("kind", ["modify", "create", "delete"])
def test_process_death_between_writes_recovers_from_a_new_process(project, tmp_path, kind, direction):
    first = proposal(tmp_path, "first.py", None if kind == "delete" else "value = 2\n")
    if kind == "create":
        first = proposal(tmp_path, "created.py", "created = True\n")
    changes = (first, proposal(tmp_path, "nested/second.py", "second = 2\n"))
    service = RecoverableChanges(project)
    plan = service.prepare("process-death", changes=changes)
    if direction == "rollback":
        assert service.run(plan.plan_id).status == "applied"
    script = """
import os, sys
from pathlib import Path
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.project import Project
from selene.edit_plans.service import RecoverableChanges
from solidlsp.ls_config import LanguageServerId
class ExitAfterFile:
    def after_file(self, path, direction):
        os._exit(73)
root, plan, action, crash = sys.argv[1:]
p = Project(project_root=root, project_config=ProjectConfig(project_name="recoverable-changes", language_servers=[LanguageServerId.PYTHON]), selene_config=SeleneConfig().with_headless_mode_overrides())
result = RecoverableChanges(p, observer=ExitAfterFile() if crash == "yes" else None).run(plan, action=action)
print(result.status)
p.shutdown()
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    command = [sys.executable, "-c", script, str(tmp_path), plan.plan_id, direction]
    died = subprocess.run([*command, "yes"], check=False, capture_output=True, text=True, env=environment, timeout=20)
    assert died.returncode == 73, died.stderr
    resumed = subprocess.run([*command, "no"], check=False, capture_output=True, text=True, env=environment, timeout=20)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == ("applied" if direction == "apply" else "rolled_back")
    if direction == "rollback":
        assert (tmp_path / "first.py").read_bytes() == b"value = 1\r\n"
        assert (tmp_path / "nested" / "second.py").read_text() == "second = 1\n"
    else:
        assert (tmp_path / "nested" / "second.py").read_text() == "second = 2\n"


def test_overlapping_service_cannot_mutate_while_another_apply_owns_the_project(project, tmp_path):
    class TryOverlappingApply:
        def after_file(self, path, direction):
            with pytest.raises(ChangeConflict, match="owns this project"):
                RecoverableChanges(project).run(plan.plan_id)

    service = RecoverableChanges(project, observer=TryOverlappingApply())
    plan = service.prepare("ownership", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    assert service.run(plan.plan_id).status == "applied"


def test_changed_or_missing_recovery_bodies_do_not_authorize_a_write(project, tmp_path):
    service = RecoverableChanges(project)
    plan = service.prepare("tampered-body", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    journal = tmp_path / plan.recovery_directory
    original = b"value = 1\r\n"
    for retained in journal.iterdir():
        if retained.is_file() and retained.read_bytes() == original:
            retained.write_bytes(b"wrong snapshot\n")
            break
    with pytest.raises(ChangeConflict, match="snapshot"):
        service.run(plan.plan_id)
    assert (tmp_path / "first.py").read_bytes() == original


def test_hardlink_alias_cannot_silently_diverge_from_its_other_name(project, tmp_path):
    linked = tmp_path.parent / (tmp_path.name + "-linked.py")
    os.link(tmp_path / "first.py", linked)
    try:
        with pytest.raises(ChangeInputError, match="hard-link"):
            RecoverableChanges(project).prepare("hard-link", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
        assert linked.read_bytes() == b"value = 1\r\n"
    finally:
        linked.unlink()


def test_journal_is_excluded_from_normal_git_add_and_remains_private(project, tmp_path):
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "init", "--template="], cwd=tmp_path, env=environment, check=True, capture_output=True)
    plan = RecoverableChanges(project).prepare("private-journal", changes=(proposal(tmp_path, "first.py", "value = 2\n"),))
    journal = tmp_path / plan.recovery_directory
    assert journal.stat().st_mode & 0o777 == 0o700
    retained = [path for path in journal.iterdir() if path.is_file()]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        input="\n".join(path.relative_to(tmp_path).as_posix() for path in retained) + "\n",
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(result.stdout.splitlines()) == {path.relative_to(tmp_path).as_posix() for path in retained}
