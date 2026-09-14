import hashlib
import os
import shutil
from pathlib import Path

import pytest

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.context.model import SourceReference
from selene.memories.evidence import MemoryDocument, MemoryEvidenceRequest
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


def make_project(root: Path, **configuration) -> Project:
    return Project(
        project_root=str(root),
        project_config=ProjectConfig(project_name="evidence-test", language_servers=[LanguageServerId.PYTHON], **configuration),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cache.py").write_text("CACHE_TTL = 60\n# source-only-canary\n")
    project = make_project(tmp_path)
    yield project
    project.shutdown()


def reference(root: Path, path="src/cache.py", start=1, end=1) -> SourceReference:
    return SourceReference(path, hashlib.sha256((root / path).read_bytes()).hexdigest(), start, end)


def record(project, root, name="architecture/cache", content="Keep cache expiry explicit.", **options):
    request = MemoryEvidenceRequest("team:platform", (reference(root),), scope="src", **options)
    project.memory_manager.save_memory(name, content, True, provenance=request)
    return project.memory_manager.assess_memory(name)


def test_record_binds_owner_scope_source_and_body_without_copying_source_text(project, tmp_path):
    assessment = record(project, tmp_path)
    manager = project.memory_manager
    path = manager.get_memory_file_path("architecture/cache")
    assert assessment.status == "current"
    assert assessment.provenance.owner == "team:platform"
    assert assessment.provenance.scope == "src"
    assert assessment.memory_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = manager.load_memory("architecture/cache")
    assert '"status": "current"' in loaded and "Keep cache expiry explicit." in loaded
    assert "source-only-canary" not in path.read_text()
    assert manager.list_project_memories().get_full_list() == ["architecture/cache"]


def test_preserved_timestamp_source_changes_and_reverts_are_observed(project, tmp_path):
    record(project, tmp_path)
    path = tmp_path / "src" / "cache.py"
    before = path.read_bytes()
    stamp = path.stat()
    path.write_bytes(before.replace(b"60", b"90"))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    stale = project.memory_manager.assess_memory("architecture/cache")
    assert stale.status == "stale"
    assert any(issue.reason == "source_changed" for issue in stale.issues)
    assert '"status": "stale"' in project.memory_manager.load_memory("architecture/cache")
    path.write_bytes(before)
    assert project.memory_manager.assess_memory("architecture/cache").status == "current"


@pytest.mark.parametrize("change", ["delete", "exclude", "symlink"])
def test_missing_excluded_and_retargeted_evidence_is_not_silently_current(project, tmp_path, change):
    record(project, tmp_path)
    path = tmp_path / "src" / "cache.py"
    if change == "delete":
        path.unlink()
    elif change == "exclude":
        (tmp_path / ".gitignore").write_text("src/cache.py\n")
    else:
        target = tmp_path / "other.py"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    assert project.memory_manager.assess_memory("architecture/cache").status == "stale"


def test_body_edits_require_review_with_new_evidence_and_current_memory_version(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    old = manager.assess_memory("architecture/cache")
    manager.edit_memory("architecture/cache", "expiry", "lifetime", "literal", False, True)
    assert manager.assess_memory("architecture/cache").status == "needs_review"
    request = MemoryEvidenceRequest("team:reviewer", (reference(tmp_path),), scope="src")
    with pytest.raises(ValueError, match="version conflict"):
        manager.review_memory("architecture/cache", request, old.memory_sha256)
    current = manager.assess_memory("architecture/cache")
    reviewed = manager.review_memory("architecture/cache", request, current.memory_sha256)
    assert reviewed.status == "current"
    assert reviewed.provenance.owner == "team:reviewer"
    assert manager.load_memory_content("architecture/cache") == "Keep cache lifetime explicit."


def test_stale_references_cannot_be_refreshed_without_supplied_current_versions(project, tmp_path):
    previous_reference = reference(tmp_path)
    record(project, tmp_path)
    (tmp_path / "src" / "cache.py").write_text("CACHE_TTL = 90\n")
    manager = project.memory_manager
    stale = manager.assess_memory("architecture/cache")
    with pytest.raises(ValueError, match="not current"):
        manager.review_memory("architecture/cache", MemoryEvidenceRequest("team:platform", (previous_reference,)), stale.memory_sha256)
    assert manager.assess_memory("architecture/cache").status == "stale"
    new = manager.review_memory("architecture/cache", MemoryEvidenceRequest("team:platform", (reference(tmp_path),)), stale.memory_sha256)
    assert new.status == "current"


def test_copied_project_record_withholds_body_until_explicit_adoption(project, tmp_path):
    record(project, tmp_path, content="COMPANY_A_DECISION_CANARY")
    copied = tmp_path.parent / (tmp_path.name + "-company-b")
    shutil.copytree(tmp_path, copied)
    other = make_project(copied)
    try:
        manager = other.memory_manager
        assessment = manager.assess_memory("architecture/cache")
        assert assessment.status == "scope_mismatch"
        assert assessment.provenance is None
        assert "COMPANY_A_DECISION_CANARY" not in manager.load_memory("architecture/cache")
        assert manager.load_memory_for_editing("architecture/cache").content == ""
        request = MemoryEvidenceRequest("team:company-b", (reference(copied),))
        with pytest.raises(ValueError, match="adopt_project"):
            manager.review_memory("architecture/cache", request, assessment.memory_sha256)
        adopted = manager.review_memory("architecture/cache", request, assessment.memory_sha256, adopt_project=True)
        assert adopted.status == "current"
        assert "COMPANY_A_DECISION_CANARY" in manager.load_memory("architecture/cache")
    finally:
        other.shutdown()


def test_provenance_cannot_move_into_global_scope_or_escape_via_memory_symlink(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    with pytest.raises(ValueError, match="global"):
        manager.move_memory("architecture/cache", "global/copied", True)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    memories = manager.get_memory_file_path("placeholder").parent
    (memories / "shared").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical"):
        manager.save_memory("shared/decision", "local decision", True, provenance=MemoryEvidenceRequest("team", (reference(tmp_path),)))
    assert list(outside.iterdir()) == []
    assert manager.assess_memory("architecture/cache").status == "current"


def test_symlinked_foreign_memory_does_not_bypass_body_withholding(project, tmp_path):
    record(project, tmp_path, content="FOREIGN_SOURCE_CANARY")
    source = project.memory_manager.get_memory_file_path("architecture/cache")
    other_root = tmp_path.parent / (tmp_path.name + "-other")
    other_root.mkdir()
    other = make_project(other_root)
    try:
        path = other.memory_manager.get_memory_file_path("foreign")
        path.symlink_to(source)
        assert "FOREIGN_SOURCE_CANARY" not in other.memory_manager.load_memory("foreign")
        assert other.memory_manager.load_memory_content("foreign") == ""
    finally:
        other.shutdown()


def test_plain_write_preserves_provenance_but_requires_body_review(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    manager.save_memory("architecture/cache", "A different claim.", True)
    assessment = manager.assess_memory("architecture/cache")
    assert assessment.status == "needs_review"
    assert assessment.provenance.owner == "team:platform"
    assert len(assessment.provenance.evidence) == 1


def test_reference_maintenance_edits_body_only_and_keeps_owner_declaration(project, tmp_path):
    manager = project.memory_manager
    manager.save_memory("old", "A referenced note.", True)
    manager.save_memory(
        "dependent",
        "Read `mem:old`.",
        True,
        provenance=MemoryEvidenceRequest("team mem:old", (reference(tmp_path),)),
    )
    message, count = manager.rename_memory_and_propagate_references("old", "new", True)
    assert count == 1 and "renamed" in message
    assert manager.load_memory_content("dependent") == "Read `mem:new`."
    assessment = manager.assess_memory("dependent")
    assert assessment.status == "needs_review"
    assert assessment.provenance.owner == "team mem:old"
    assert manager.validate_referential_integrity(False, False).stale_references == []


def test_expiration_and_human_decisions_without_evidence_are_explicit(project, tmp_path):
    expired = record(project, tmp_path, expires_at="2000-01-01T00:00:00+00:00")
    assert expired.status == "expired"
    manager = project.memory_manager
    manager.save_memory(
        "policy", "Prefer explicit review.", True, provenance=MemoryEvidenceRequest("declared-owner", (), origin="human_decision")
    )
    decision = manager.assess_memory("policy")
    assert decision.status == "unverified"
    assert decision.provenance.origin == "human_decision"
    with pytest.raises(ValueError, match="timezone"):
        record(project, tmp_path, name="invalid-expiry", expires_at="2000-01-01")


def test_legacy_content_stays_readable_and_upgrade_requires_its_current_hash(project, tmp_path):
    manager = project.memory_manager
    manager.save_memory("legacy", "Legacy Markdown.", True)
    assert manager.load_memory("legacy") == "Legacy Markdown."
    assessment = manager.assess_memory("legacy")
    assert assessment.status == "unverified"
    with pytest.raises(ValueError, match="version conflict"):
        manager.save_memory("legacy", "Reviewed Markdown.", True, provenance=MemoryEvidenceRequest("owner", (reference(tmp_path),)))
    manager.save_memory(
        "legacy",
        "Reviewed Markdown.",
        True,
        provenance=MemoryEvidenceRequest("owner", (reference(tmp_path),)),
        expected_memory_sha256=assessment.memory_sha256,
    )
    assert manager.assess_memory("legacy").status == "current"


def test_read_only_and_ignored_memory_rules_apply_to_provenance_and_review(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\n")
    project = make_project(tmp_path, read_only_memory_patterns=["protected"], ignored_memory_patterns=["hidden"])
    try:
        manager = project.memory_manager
        request = MemoryEvidenceRequest("owner", (reference(tmp_path, "code.py"),))
        manager.save_memory("protected", "Protected decision.", False, provenance=request)
        existing = manager.assess_memory("protected")
        with pytest.raises(PermissionError):
            manager.review_memory("protected", request, existing.memory_sha256)
        with pytest.raises(PermissionError):
            manager.move_memory("protected", "unprotected", True)
        with pytest.raises(ValueError, match="ignored"):
            manager.save_memory("hidden", "Hidden decision.", True, provenance=request)
    finally:
        project.shutdown()


def test_manually_changed_crlf_body_is_review_required_and_raw_hash_is_exact(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    path = manager.get_memory_file_path("architecture/cache")
    document = MemoryDocument.parse(path.read_text())
    path.write_bytes(MemoryDocument(document.content + "\n", document.provenance).serialize().replace("\n", "\r\n").encode())
    assessment = manager.assess_memory("architecture/cache")
    assert assessment.status == "needs_review"
    assert assessment.memory_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "Keep cache expiry explicit." in manager.load_memory("architecture/cache")


def test_metadata_markup_remains_data_and_round_trips_without_ending_the_header(project, tmp_path):
    manager = project.memory_manager
    owner = 'team --><img src="https://example.invalid/metadata">'
    manager.save_memory("markup", "A local decision.", True, provenance=MemoryEvidenceRequest(owner, (reference(tmp_path),)))
    raw = manager.get_memory_file_path("markup").read_text()
    assert MemoryDocument.parse(raw).provenance.owner == owner
    assert raw.count("-->") == 1
    loaded = manager.load_memory("markup")
    assert "```json\n" in loaded
    assert "<img src=" not in loaded


def test_invalid_reference_range_and_declared_scope_are_rejected_before_recording(project, tmp_path):
    manager = project.memory_manager
    for request in (
        MemoryEvidenceRequest("owner", (reference(tmp_path, end=50),)),
        MemoryEvidenceRequest("owner", (reference(tmp_path),), scope="unrelated"),
    ):
        with pytest.raises(ValueError, match="not current"):
            manager.save_memory("invalid-reference", "An unsupported decision.", True, provenance=request)
    assert manager.list_project_memories().get_full_list() == []


def test_alias_of_project_root_does_not_turn_its_own_memories_into_foreign_records(project, tmp_path):
    record(project, tmp_path)
    alias = tmp_path.parent / (tmp_path.name + "-alias")
    alias.symlink_to(tmp_path, target_is_directory=True)
    same = make_project(alias)
    try:
        assert same.memory_manager.assess_memory("architecture/cache").status == "current"
        assert "Keep cache expiry explicit." in same.memory_manager.load_memory("architecture/cache")
    finally:
        same.shutdown()


def test_dashboard_edits_body_without_saving_assessment_text_and_rejects_stale_versions(project, tmp_path):
    from types import SimpleNamespace

    from selene.dashboard import SeleneDashboardAPI

    class DashboardAgent:
        def register_config_changed_callback(self, callback):
            pass

        def get_active_project(self):
            return project

        def execute_task(self, callback, **options):
            return callback()

    record(project, tmp_path)
    api = SeleneDashboardAPI(SimpleNamespace(), [], DashboardAgent())
    client = api._app.test_client()
    loaded = client.post("/get_memory", json={"memory_name": "architecture/cache"}).get_json()
    assert loaded["content"] == "Keep cache expiry explicit."
    assert loaded["evidence_status"] == "current"
    assert not loaded["content_withheld"]
    saved = client.post(
        "/save_memory",
        json={
            "memory_name": "architecture/cache",
            "content": "A reviewed UI edit.",
            "expected_memory_sha256": loaded["memory_sha256"],
        },
    ).get_json()
    assert saved["status"] == "success"
    assert project.memory_manager.load_memory_content("architecture/cache") == "A reviewed UI edit."
    changed = client.post("/get_memory", json={"memory_name": "architecture/cache"}).get_json()
    assert changed["evidence_status"] == "needs_review"
    conflict = client.post(
        "/save_memory",
        json={
            "memory_name": "architecture/cache",
            "content": "Overwrite from stale UI.",
            "expected_memory_sha256": loaded["memory_sha256"],
        },
    ).get_json()
    assert conflict["status"] == "error" and "version conflict" in conflict["message"]
    assert project.memory_manager.load_memory_content("architecture/cache") == "A reviewed UI edit."


def test_editor_bom_and_leading_whitespace_do_not_disable_provenance(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    path = manager.get_memory_file_path("architecture/cache")
    path.write_bytes(b"\xef\xbb\xbf\n\n" + path.read_bytes())
    assert manager.assess_memory("architecture/cache").status == "current"
    (tmp_path / "src" / "cache.py").write_text("CACHE_TTL = 90\n")
    assert manager.assess_memory("architecture/cache").status == "stale"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes are a POSIX fixture")
def test_memory_named_pipe_is_rejected_without_waiting_for_a_writer(project):
    manager = project.memory_manager
    path = manager.get_memory_file_path("pipe")
    os.mkfifo(path)
    with pytest.raises(OSError, match="regular"):
        manager.load_memory("pipe")


def test_dot_segments_cannot_bypass_named_memory_rules(project):
    with pytest.raises(ValueError, match="dot path segments"):
        project.memory_manager.save_memory("protected/./decision", "A changed claim.", True)


def test_full_memory_store_requires_explicit_removal_and_still_allows_existing_reviews(project, tmp_path):
    record(project, tmp_path, expires_at="2000-01-01T00:00:00+00:00")
    manager = project.memory_manager
    raw = manager.get_memory_file_path("architecture/cache").read_bytes()
    for index in range(255):
        manager.get_memory_file_path(f"archive/decision-{index}").write_bytes(raw)
    with pytest.raises(ValueError, match="256 evidence-backed memories"):
        record(project, tmp_path, name="new-decision")
    current = manager.assess_memory("architecture/cache")
    reviewed = manager.review_memory("architecture/cache", MemoryEvidenceRequest("owner", (reference(tmp_path),)), current.memory_sha256)
    assert reviewed.status == "current"
    assert manager.assess_memory("archive/decision-1").status == "expired"
    manager.delete_memory("archive/decision-0", is_tool_context=True)
    assert record(project, tmp_path, name="new-decision").status == "current"
    assert len(manager.list_project_memories()) == 256


def test_oversized_body_edit_keeps_the_existing_decision_and_provenance(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    path = manager.get_memory_file_path("architecture/cache")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="16000"):
        manager.save_memory("architecture/cache", "x" * 16001, True)
    assert path.read_bytes() == before
    assert manager.assess_memory("architecture/cache").status == "current"


def test_unknown_provenance_format_fails_instead_of_exposing_an_unassessed_claim(project, tmp_path):
    record(project, tmp_path)
    manager = project.memory_manager
    path = manager.get_memory_file_path("architecture/cache")
    path.write_text(path.read_text().replace("selene-evidence:v1", "selene-evidence:v9", 1))
    with pytest.raises(ValueError, match="Unsupported memory provenance format"):
        manager.load_memory("architecture/cache")
