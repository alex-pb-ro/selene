"""Focused local lexical retrieval with explicit source versions and index coverage."""

from dataclasses import asdict

from selene.tools import Tool, ToolMarkerOptional


class SearchIndexTool(Tool, ToolMarkerOptional):
    """Search locally indexed code and documentation, returning current source lines and hashes."""

    def apply(self, query: str, relative_path: str = "", limit: int = 10, reconcile: bool = False, max_answer_chars: int = -1) -> str:
        """Find files by words or identifier components using the project's local index.

        :param query: 1-64 words or identifier components; matches are ranked by term overlap
        :param relative_path: optional project-relative file or directory scope
        :param limit: maximum number of matching files, from 1 to 50
        :param reconcile: refresh every included file before searching, including changes that produced no filesystem event
        :param max_answer_chars: maximum response length; -1 uses the configured limit
        :return: matches with SHA-256 versions and 1-based lines, plus index generation and coverage
        """
        result = self.project.get_local_index().search(query, relative_path=relative_path, limit=limit, reconcile=reconcile)
        return self._limit_length(self._to_json(asdict(result)), max_answer_chars)
