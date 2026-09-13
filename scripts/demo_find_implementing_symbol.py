"""
Demonstrates FindImplementationsTool on the Go test repository.
"""

import json
from pathlib import Path
from pprint import pprint

from selene.agent import SeleneAgent
from selene.config.selene_config import LanguageBackend, ProjectConfig, RegisteredProject, SeleneConfig
from selene.constants import REPO_ROOT
from selene.project import Project
from selene.tools import FindImplementationsTool
from solidlsp.ls_config import LanguageServerId

SEPARATOR = "=" * 80
GO_TEST_REPO = Path(REPO_ROOT) / "test" / "resources" / "repos" / "go" / "test_repo"


def make_agent(project_root: Path, language: LanguageServerId, project_name: str) -> SeleneAgent:
    """Create an LSP-backed Selene agent for a single explicit project."""
    selene_config = SeleneConfig.from_config_file()
    selene_config.web_dashboard = False
    selene_config.language_backend = LanguageBackend.LSP

    project = Project(
        project_root=str(project_root),
        project_config=ProjectConfig(
            project_name=project_name,
            language_servers=[language],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        ),
        selene_config=selene_config,
    )
    selene_config.projects = [RegisteredProject.from_project_instance(project)]
    return SeleneAgent(project=project_name, selene_config=selene_config)


def print_section(title: str) -> None:
    """Print a visibly separated section header."""
    print(f"\n{SEPARATOR}")
    print(title)
    print(SEPARATOR)


if __name__ == "__main__":
    agent = make_agent(GO_TEST_REPO, LanguageServerId.GO, "demo_go_test_repo")

    try:
        # letting the language server finish startup
        agent.execute_task(lambda: None)

        # running the implementation lookup
        find_implementations_tool = agent.get_tool(FindImplementationsTool)
        result = agent.execute_task(
            lambda: find_implementations_tool.apply(
                name_path="Greeter/FormatGreeting",
                relative_path="main.go",
                include_info=True,
            )
        )

        print_section("Find Implementations Result")
        implementations = json.loads(result)
        pprint(implementations, width=200)

        # validating the demonstrated result
        assert any(implementation["name_path"] == "(ConsoleGreeter).FormatGreeting" for implementation in implementations), result
        print("\nVerified implementation target: (ConsoleGreeter).FormatGreeting")
    finally:
        agent.shutdown()
