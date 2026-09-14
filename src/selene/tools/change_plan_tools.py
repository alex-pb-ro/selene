"""Prepare and recover coordinated file changes under the client's existing authorization."""

import json
from dataclasses import asdict
from typing import Literal

from selene.changes.model import ProposedFileChange
from selene.edit_plans.service import RecoverableChanges
from selene.tools import Tool, ToolMarkerCanEdit, ToolMarkerOptional


class PrepareChangeTool(Tool, ToolMarkerCanEdit, ToolMarkerOptional):
    """Prepare a source-versioned text change and persist its local recovery contents."""

    def apply(
        self, request_id: str, diff: str = "", changes: list[ProposedFileChange] | None = None, allow_syntax_errors: bool = False
    ) -> str:
        """Stage a proposal without changing its source files.

        :param request_id: client-generated stable ID for this proposal; reuse it only with identical inputs
        :param diff: unapplied unified text diff matching the current source; supply either diff or changes
        :param changes: up to sixteen whole-file replacements/creations/deletions with SHA-256 preconditions
        :param allow_syntax_errors: explicitly allow apply despite reported Python/JSON syntax errors
        :return: durable plan ID, affected paths, source observations, syntax diagnostics and recovery limits
        """
        result = RecoverableChanges(self.project).prepare(
            request_id, diff=diff, changes=tuple(changes or ()), allow_syntax_errors=allow_syntax_errors
        )
        return json.dumps(asdict(result), ensure_ascii=True)


class ApplyChangeTool(Tool, ToolMarkerCanEdit, ToolMarkerOptional):
    """Apply a prepared plan once, preserving displaced files and reporting partial failures."""

    def apply(self, plan_id: str) -> str:
        """Apply or resume the plan under the connected client's authorization.

        :param plan_id: exact ID returned by prepare_change; repeated calls reconcile existing operations
        :return: per-file applied/conflict/failure states and retained recovery location
        """
        return json.dumps(asdict(RecoverableChanges(self.project).run(plan_id)), ensure_ascii=True)


class RecoverChangeTool(Tool, ToolMarkerCanEdit, ToolMarkerOptional):
    """Inspect or roll back a prepared change without overwriting later observed edits."""

    def apply(self, plan_id: str, action: Literal["inspect", "rollback"] = "inspect") -> str:
        """Recover after cancellation, process death or a partial failure.

        :param plan_id: exact ID returned by prepare_change
        :param action: inspect current file states or roll back applied files in reverse order
        :return: per-file recovery outcomes; conflicts retain their local original/proposed/displaced versions
        """
        return json.dumps(asdict(RecoverableChanges(self.project).run(plan_id, action=action)), ensure_ascii=True)
