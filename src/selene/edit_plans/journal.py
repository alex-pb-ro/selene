"""Content-bound manifests and append-only intent records in private project storage."""

import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from selene.changes.model import ChangeConflict, ChangedRange, ChangeInputError
from selene.edit_plans.filesystem import FileState, PlanDirectory
from selene.edit_plans.model import PlanDiagnostic, PlanEntry, PlanManifest, StepIntent


class PlanJournal:
    """Serialize project writers and authenticate immutable plan contents against the client's handle.

    Mutable operation results are inferred from retained inodes; they are never trusted as
    permission to overwrite a source. Journal data is local, contains source bodies, and
    remains until explicitly removed after review.
    """

    def __init__(self, directory: PlanDirectory):
        self.directory = directory

    @staticmethod
    def encode(value: Any) -> bytes:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def request_digest(request_id: str) -> str:
        if not 1 <= len(request_id) <= 128:
            raise ChangeInputError("request_id must contain between one and 128 characters")
        return PlanJournal.digest(request_id.encode("utf-8"))

    @staticmethod
    @contextmanager
    def locked(root: PlanDirectory) -> Iterator[PlanDirectory]:
        import fcntl

        with root.child(".selene", create=True) as metadata:
            with metadata.child("change-plans", create=True, private=True) as storage:
                try:
                    storage.write_new(".gitignore", b"*\n")
                except FileExistsError:
                    if storage.read(".gitignore") != b"*\n":
                        raise ChangeInputError("Recovery storage must retain its Git exclusion")
                try:
                    storage.write_new("lock", b"")
                except FileExistsError:
                    pass
                with storage.file("lock") as descriptor:
                    state = FileState.read(descriptor)
                    if state.uid != os.geteuid() or state.mode & 0o077:
                        raise ChangeInputError("Recovery lock must be owned and private")
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise ChangeConflict("Another recoverable change operation owns this project; retry after it completes") from error
                    try:
                        yield storage
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def save_manifest(self, manifest: PlanManifest) -> str:
        content = self.encode(asdict(manifest))
        if len(content) > 256 * 1024:
            raise ChangeInputError("Prepared plan metadata exceeds the 256 KiB allowance")
        self.directory.write_new("manifest.json", content)
        return manifest.request_digest + "." + self.digest(content)

    def load_manifest(self, plan_id: str | None = None) -> PlanManifest:
        content = self.directory.read("manifest.json", max_bytes=256 * 1024)
        raw = json.loads(content)
        if plan_id is not None and plan_id != raw["request_digest"] + "." + self.digest(content):
            raise ChangeConflict("Plan manifest changed; its contents no longer match the supplied plan ID")
        if raw["version"] != 1:
            raise ChangeInputError("Unsupported recovery plan version")
        entries = tuple(
            PlanEntry(
                path=value["path"],
                kind=value["kind"],
                before=None if value["before"] is None else FileState(**value["before"]),
                proposed_sha256=value["proposed_sha256"],
                staged=None if value["staged"] is None else FileState(**value["staged"]),
                parent_device=value["parent_device"],
                parent_inode=value["parent_inode"],
                ranges=tuple(ChangedRange(**span) for span in value["ranges"]),
            )
            for value in raw.pop("entries")
        )
        diagnostics = tuple(PlanDiagnostic(**value) for value in raw.pop("diagnostics"))
        return PlanManifest(**raw, entries=entries, diagnostics=diagnostics)

    @staticmethod
    def directory_name(plan_id: str) -> str:
        if re.fullmatch(r"[a-f0-9]{64}\.[a-f0-9]{64}", plan_id) is None:
            raise ChangeInputError("Invalid plan ID")
        return plan_id.split(".")[0]

    def load_intent(self, entry: int, direction: str) -> StepIntent | None:
        try:
            raw = json.loads(self.directory.read(f"{direction}-{entry}.json", max_bytes=8192))
        except FileNotFoundError:
            return None
        raw["target_before"] = None if raw["target_before"] is None else FileState(**raw["target_before"])
        raw["slot_before"] = None if raw["slot_before"] is None else FileState(**raw["slot_before"])
        return StepIntent(**raw)

    def save_intent(self, intent: StepIntent) -> None:
        self.directory.write_new(f"{intent.direction}-{intent.entry}.json", self.encode(asdict(intent)))

    def body(self, index: int, version: str, expected_sha256: str | None) -> bytes | None:
        if expected_sha256 is None:
            return None
        content = self.directory.read(f"{version}-{index}")
        if self.digest(content) != expected_sha256:
            raise ChangeConflict("A retained source snapshot changed; manual recovery is required")
        return content

    def validate_project(self, manifest: PlanManifest, root: PlanDirectory, path: Path) -> None:
        if str(path) != manifest.project_root or root.identity != (manifest.root_device, manifest.root_inode):
            raise ChangeConflict("The recovery plan belongs to a different project directory; it cannot be replayed here")
