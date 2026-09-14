"""Strict unified-diff decoding and exact application to an in-memory source snapshot."""

import json
import re
from dataclasses import dataclass, replace

from selene.changes.model import ChangeConflict, ChangeInputError
from selene.util.cancellation import CancellationToken


@dataclass(frozen=True)
class PatchLine:
    operation: str
    content: str


@dataclass(frozen=True)
class PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[PatchLine, ...]


@dataclass(frozen=True)
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[PatchHunk, ...]

    @property
    def path(self) -> str:
        path = self.old_path if self.old_path is not None else self.new_path
        assert path is not None
        return path

    def apply(self, original: str | None) -> str | None:
        """Apply exact hunks in memory, rejecting shifted context and contradictory counts."""
        if (original is None) != (self.old_path is None):
            raise ChangeConflict(f"Patch existence precondition failed: {self.path}")
        before = [] if original is None else original.splitlines(keepends=True)
        result: list[str] = []
        cursor = 0
        for hunk in self.hunks:
            CancellationToken.check_current()
            start = hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
            if start < cursor or start > len(before):
                raise ChangeConflict(f"Overlapping or out-of-range patch hunk: {self.path}")
            result.extend(before[cursor:start])
            expected_new_start = hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
            if len(result) != expected_new_start:
                raise ChangeInputError(f"Inconsistent new-line coordinates: {self.path}")
            cursor = start
            for line in hunk.lines:
                if line.operation in {" ", "-"}:
                    if cursor >= len(before) or before[cursor] != line.content:
                        raise ChangeConflict(f"Patch context does not match the current source: {self.path}")
                    cursor += 1
                if line.operation in {" ", "+"}:
                    result.append(line.content)
        result.extend(before[cursor:])
        if self.new_path is None:
            if result:
                raise ChangeInputError(f"A deletion patch must remove the complete file: {self.path}")
            return None
        return "".join(result)


class UnifiedDiff:
    """Parse text-only unified diffs; never execute Git, external filters or patch commands."""

    _HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
    _METADATA = ("diff --git ", "index ", "new file mode ", "deleted file mode ")

    @staticmethod
    def _path(header: str, prefix: str) -> str | None:
        value = header[len(prefix) :].rstrip("\n").split("\t", 1)[0]
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except (ValueError, TypeError) as error:
                raise ChangeInputError("Unsupported quoted patch path; use structured file changes") from error
            if not isinstance(value, str):
                raise ChangeInputError("Invalid quoted patch path")
        if value == "/dev/null":
            return None
        if not value or "\x00" in value:
            raise ChangeInputError("Patch paths must be non-empty and contain no NUL characters")
        return value

    @classmethod
    def parse(cls, text: str) -> tuple[FilePatch, ...]:
        if len(text.encode("utf-8")) > 8 * 1024 * 1024:
            raise ChangeInputError("Diff input exceeds the 8 MiB allowance")
        lines = text.splitlines(keepends=True)
        patches = []
        seen = set()
        position = 0
        while position < len(lines):
            CancellationToken.check_current()
            line = lines[position]
            if line.startswith(cls._METADATA) or not line.strip():
                position += 1
                continue
            if not line.startswith("--- ") or position + 1 >= len(lines) or not lines[position + 1].startswith("+++ "):
                raise ChangeInputError("Expected unified-diff file headers; binary, mode-only, copy and rename patches are unsupported")
            old_path = cls._path(line, "--- ")
            new_path = cls._path(lines[position + 1], "+++ ")
            if (old_path is None or old_path.startswith("a/")) and (new_path is None or new_path.startswith("b/")):
                old_path = None if old_path is None else old_path[2:]
                new_path = None if new_path is None else new_path[2:]
            if old_path is None and new_path is None:
                raise ChangeInputError("A patch must identify a source or destination path")
            if old_path is not None and new_path is not None and old_path != new_path:
                raise ChangeInputError("Represent a rename as a deletion and creation in structured file changes")
            path = old_path if old_path is not None else new_path
            if path in seen:
                raise ChangeInputError("Each changed path must occur once")
            seen.add(path)
            position += 2
            hunks = []
            while position < len(lines) and lines[position].startswith("@@ "):
                match = cls._HEADER.fullmatch(lines[position].rstrip("\r\n"))
                if match is None:
                    raise ChangeInputError("Malformed unified-diff hunk header")
                old_start, old_count, new_start, new_count = (int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
                if (old_count and old_start == 0) or (new_count and new_start == 0):
                    raise ChangeInputError("Non-empty diff ranges must start at a 1-based line")
                position += 1
                payload: list[PatchLine] = []
                old_seen = new_seen = 0
                while position < len(lines):
                    if position % 100 == 0:
                        CancellationToken.check_current()
                    part = lines[position]
                    if part.rstrip("\r\n") == "\\ No newline at end of file":
                        if not payload or not payload[-1].content.endswith("\n"):
                            raise ChangeInputError("Unexpected no-newline marker")
                        payload[-1] = replace(payload[-1], content=payload[-1].content.removesuffix("\n"))
                        position += 1
                        continue
                    if old_seen == old_count and new_seen == new_count:
                        break
                    if not part or part[0] not in {" ", "+", "-"}:
                        raise ChangeInputError("Diff hunk is shorter than its declared ranges")
                    operation = part[0]
                    old_seen += operation in {" ", "-"}
                    new_seen += operation in {" ", "+"}
                    if old_seen > old_count or new_seen > new_count:
                        raise ChangeInputError("Diff hunk exceeds its declared ranges")
                    payload.append(PatchLine(operation, part[1:]))
                    position += 1
                if old_seen != old_count or new_seen != new_count:
                    raise ChangeInputError("Incomplete unified-diff hunk")
                hunks.append(PatchHunk(old_start, old_count, new_start, new_count, tuple(payload)))
                if len(hunks) > 256:
                    raise ChangeInputError("At most 256 hunks per file are supported")
            if not hunks:
                raise ChangeInputError("A file patch must contain text hunks")
            patches.append(FilePatch(old_path, new_path, tuple(hunks)))
            if len(patches) > 16:
                raise ChangeInputError("At most sixteen changed files are supported")
        if not patches:
            raise ChangeInputError("The diff contains no text changes")
        return tuple(patches)
