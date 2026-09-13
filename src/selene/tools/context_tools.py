"""Versioned, project-local context retrieval with bounded JSON output."""

from selene.context.model import ContextAnchor
from selene.tools import Tool, ToolMarkerOptional


class FindContextTool(Tool, ToolMarkerOptional):
    """Bundle relevant code, dependencies, tests and documentation with source evidence."""

    def apply(
        self,
        query: str = "",
        anchors: list[ContextAnchor] | None = None,
        scope: str = "",
        max_chars: int = 20000,
        include_bodies: bool = True,
    ) -> str:
        """Retrieve bounded local context, distinguishing semantic evidence from name matches.

        :param query: search words or identifier components; may be empty when anchors are provided
        :param anchors: up to eight project-relative paths with optional symbol name paths
        :param scope: optional project-relative file or directory containing all returned items
        :param max_chars: total JSON character allowance including metadata, from 2048 to 100000
        :param include_bodies: include bounded excerpts; omitted and partial bodies are explicitly marked
        :return: versioned items, evidence, coverage limitations and an optional expiring continuation
        """
        return self.project.get_context_service().find(
            query, tuple(anchors or ()), scope=scope, max_chars=max_chars, include_bodies=include_bodies
        )


class ContinueContextTool(Tool, ToolMarkerOptional):
    """Retrieve another context page, rejecting changed sources or expired selections."""

    def apply(self, continuation: str, max_chars: int = 20000, include_bodies: bool = True) -> str:
        """Continue a project-bound selection that expires after five minutes.

        :param continuation: opaque continuation returned by find_context or continue_context
        :param max_chars: total JSON character allowance including metadata, from 2048 to 100000
        :param include_bodies: include bounded source excerpts
        :return: another version-checked page; changed selections require a fresh find_context call
        """
        return self.project.get_context_service().continue_bundle(continuation, max_chars=max_chars, include_bodies=include_bodies)


class ReadContextItemsTool(Tool, ToolMarkerOptional):
    """Read selected context bodies using the source versions attached to their bundle."""

    def apply(self, bundle_id: str, item_ids: list[str], max_chars: int = 20000) -> str:
        """Read up to 500 lines per selected item within the total output allowance.

        :param bundle_id: project-bound bundle identifier returned by find_context
        :param item_ids: one to sixteen distinct item IDs from the bundle
        :param max_chars: total JSON character allowance including metadata, from 2048 to 100000
        :return: freshly validated bodies with complete or partial status and the last included line
        """
        return self.project.get_context_service().read_items(bundle_id, tuple(item_ids), max_chars=max_chars)
