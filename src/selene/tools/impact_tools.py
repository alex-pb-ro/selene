"""Evidence-based analysis of proposed changes without applying them."""

from selene.changes.model import ProposedFileChange
from selene.impact.service import ChangeImpactAnalyzer
from selene.tools import Tool, ToolMarkerOptional


class AnalyzeChangeTool(Tool, ToolMarkerOptional):
    """Identify existing references, implementations, test candidates and unresolved impact."""

    def apply(
        self, diff: str = "", changes: list[ProposedFileChange] | None = None, scope: str = "", max_chars: int = 20000, max_depth: int = 2
    ) -> str:
        """Analyze an unapplied text proposal against current project source versions.

        :param diff: unified text diff matching current source; supply either diff or changes
        :param changes: up to sixteen replacements/deletions with expected SHA-256 hashes; null hashes require missing paths
        :param scope: optional project-relative scope for reported targets; changed sources and evidence remain project-bound
        :param max_chars: exact total JSON character allowance, from 4096 to 100000; omitted findings are counted
        :param max_depth: maximum static reference traversal depth, from one to four
        :return: changed symbols, versioned static/declared relationships, heuristic test candidates and explicit uncertainty
        """
        return ChangeImpactAnalyzer(self.project).analyze(
            diff=diff, changes=tuple(changes or ()), scope=scope, max_chars=max_chars, max_depth=max_depth
        )
