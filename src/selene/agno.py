import argparse
import logging
import os
import threading
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from dotenv import load_dotenv
from sensai.util.logging import LogTime

from selene.agent import SeleneAgent, Tool
from selene.config.context_mode import SeleneAgentContext
from selene.constants import REPO_ROOT
from selene.util.exception import show_fatal_exception_safe

log = logging.getLogger(__name__)


class SeleneAgnoToolkit(Toolkit):
    def __init__(self, selene_agent: SeleneAgent):
        super().__init__("Selene")
        for tool in selene_agent.get_exposed_tool_instances():
            self.functions[tool.get_name_from_cls()] = self._create_agno_function(tool)
        log.info("Agno agent functions: %s", list(self.functions.keys()))

    @staticmethod
    def _create_agno_function(tool: Tool) -> Function:
        def entrypoint(**kwargs: Any) -> str:
            if "kwargs" in kwargs:
                # Agno sometimes passes a kwargs argument explicitly, so we merge it
                kwargs.update(kwargs["kwargs"])
                del kwargs["kwargs"]
            log.info(f"Calling tool {tool}")
            return tool.apply_ex(log_call=True, catch_exceptions=True, **kwargs)

        function = Function.from_callable(tool.get_apply_fn())
        function.name = tool.get_name_from_cls()
        function.entrypoint = entrypoint
        function.skip_entrypoint_processing = True
        return function


class SeleneAgnoAgentProvider:
    _agent: Agent | None = None
    _lock = threading.Lock()

    @classmethod
    def get_agent(cls, model: Model) -> Agent:
        """
        Returns the singleton instance of the Selene agent or creates it with the given parameters if it doesn't exist.

        NOTE: This is very ugly with poor separation of concerns, but the way in which the Agno UI works (reloading the
            module that defines the `app` variable) essentially forces us to do something like this.

        :param model: the large language model to use for the agent
        :return: the agent instance
        """
        with cls._lock:
            if cls._agent is not None:
                return cls._agent

            # change to Selene root
            os.chdir(REPO_ROOT)

            load_dotenv()
            # Agno re-reads this variable for each run, overriding its constructor setting.
            os.environ["AGNO_TELEMETRY"] = "false"

            parser = argparse.ArgumentParser(description="Selene coding assistant")

            # Create a mutually exclusive group
            group = parser.add_mutually_exclusive_group()

            # Add arguments to the group, both pointing to the same destination
            group.add_argument(
                "--project-file",
                required=False,
                help="Path to the project (or project.yml file).",
            )
            group.add_argument(
                "--project",
                required=False,
                help="Path to the project (or project.yml file).",
            )
            args = parser.parse_args()

            args_project_file = args.project or args.project_file

            if args_project_file:
                project_file = Path(args_project_file).resolve()
                # If project file path is relative, make it absolute by joining with project root
                if not project_file.is_absolute():
                    # Get the project root directory (parent of scripts directory)
                    project_root = Path(REPO_ROOT)
                    project_file = project_root / args_project_file

                # Ensure the path is normalized and absolute
                project_file = str(project_file.resolve())
            else:
                project_file = None

            with LogTime("Loading Selene agent"):
                try:
                    selene_agent = SeleneAgent(project_file, context=SeleneAgentContext.load("agent"))
                except Exception as e:
                    show_fatal_exception_safe(e)
                    raise

            # Even though we don't want to keep history between sessions,
            # for agno-ui to work as a conversation, we use a persistent database on disk.
            # This database should be deleted between sessions.
            # Note that this might collide with custom options for the agent, like adding vector-search based tools.
            sql_db_path = (Path("temp") / "agno_agent_storage.db").absolute()
            sql_db_path.parent.mkdir(exist_ok=True)
            # delete the db file if it exists
            log.info(f"Deleting DB from PID {os.getpid()}")
            if sql_db_path.exists():
                sql_db_path.unlink()

            agno_agent = Agent(
                name="Selene",
                model=model,
                # See explanation above on why database is needed
                db=SqliteDb(db_file=str(sql_db_path)),
                description="A fully-featured coding assistant",
                tools=[SeleneAgnoToolkit(selene_agent)],
                # Tool calls will be shown in the UI since that's configurable per tool
                # To see detailed logs, you should use the selene logger (configure it in the project file path)
                markdown=True,
                system_message=selene_agent.create_system_prompt(),
                telemetry=False,
                memory_manager=MemoryManager(),
                add_history_to_context=True,
                num_history_runs=100,  # you might want to adjust this (expense vs. history awareness)
            )
            cls._agent = agno_agent
            log.info(f"Agent instantiated: {agno_agent}")

        return agno_agent
