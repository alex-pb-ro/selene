"""Version-bound Python import aliases that bridge language-server reference queries."""

import ast

from selene.context.model import SemanticNode
from selene.context.sources import ContextDocument
from selene.util.cancellation import CancellationToken


class PythonImportBindings:
    @staticmethod
    def at_reference(document: ContextDocument, line: int, column: int) -> SemanticNode | None:
        """Find a renamed import containing the reported reference position."""
        if not document.path.endswith(".py"):
            return None
        try:
            tree = ast.parse("\n".join(document.lines))
        except (SyntaxError, ValueError, RecursionError):
            return None
        for index, node in enumerate(ast.walk(tree)):
            if index % 100 == 0:
                CancellationToken.check_current()
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if not alias.asname or alias.end_lineno is None or alias.end_col_offset is None:
                    continue
                if not alias.lineno - 1 <= line <= alias.end_lineno - 1:
                    continue
                first_text = document.lines[alias.lineno - 1]
                last_text = document.lines[alias.end_lineno - 1]
                first_prefix = first_text.encode("utf-8")[: alias.col_offset].decode("utf-8")
                last_prefix = last_text.encode("utf-8")[: alias.end_col_offset].decode("utf-8")
                first_column = len(first_prefix.encode("utf-16-le")) // 2
                last_column = len(last_prefix.encode("utf-16-le")) // 2
                if (line == alias.lineno - 1 and column < first_column) or (line == alias.end_lineno - 1 and column >= last_column):
                    continue
                declaration_column = last_column - len(alias.asname.encode("utf-16-le")) // 2
                return SemanticNode(
                    document.reference(alias.lineno, alias.end_lineno, alias.asname),
                    "ImportAlias",
                    alias.end_lineno - 1,
                    declaration_column,
                )
        return None
