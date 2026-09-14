"""
This script demonstrates how to use Selene's tools locally, useful
for testing or development. Here the tools will be operation the selene repo itself.
"""

import json
from pathlib import Path
from pprint import pprint

from selene.agent import SeleneAgent
from selene.config.selene_config import LanguageBackend, SeleneConfig
from selene.constants import REPO_ROOT
from selene.tools import (
    FindFileTool,
    FindReferencingSymbolsTool,
    GetDiagnosticsForFileTool,
    JetBrainsFindSymbolTool,
    JetBrainsGetSymbolsOverviewTool,
    JetBrainsInlineSymbol,
    JetBrainsRunInspectionsTool,
    JetBrainsSafeDeleteTool,
    SearchForPatternTool,
)

if __name__ == "__main__":
    selene_config = SeleneConfig.from_config_file()
    selene_config.web_dashboard = False
    selene_config.language_backend = LanguageBackend.LSP
    # project = Path(REPO_ROOT).parent / "selene-jetbrains-plugin-copy"
    project = Path(REPO_ROOT)
    agent = SeleneAgent(project=str(project), selene_config=selene_config)

    # apply a tool
    find_symbol_tool = agent.get_tool(JetBrainsFindSymbolTool)
    find_refs_tool = agent.get_tool(FindReferencingSymbolsTool)
    find_file_tool = agent.get_tool(FindFileTool)
    search_pattern_tool = agent.get_tool(SearchForPatternTool)
    overview_tool = agent.get_tool(JetBrainsGetSymbolsOverviewTool)
    safe_delete_tool = agent.get_tool(JetBrainsSafeDeleteTool)
    inline_symbol = agent.get_tool(JetBrainsInlineSymbol)
    diagnostics_in_file_tool = agent.get_tool(GetDiagnosticsForFileTool)
    jb_inspections_tool = agent.get_tool(JetBrainsRunInspectionsTool)

    result = agent.execute_task(
        lambda: diagnostics_in_file_tool.apply(
            # name_path_pattern="SeleneAgent",
            relative_path="test/resources/repos/clojure/test_repo/src/test_app/diagnostics_sample.clj",
            # keep_definition=True,
        )
    )
    pprint(json.loads(result))
    # input("Press Enter to continue...")
