import json
import logging
import threading
from typing import TYPE_CHECKING

import requests as requests_lib
from flask import Flask, request
from pydantic import BaseModel
from sensai.util.logging import LogTime

from selene.config.selene_config import LanguageBackend, SeleneConfig
from selene.constants import SelenePorts
from selene.util.http import DirectHttpSession

if TYPE_CHECKING:
    from selene.project import Project

log = logging.getLogger(__name__)

# disable Werkzeug's logging to avoid cluttering the output
logging.getLogger("werkzeug").setLevel(logging.WARNING)


class QueryProjectRequest(BaseModel):
    """
    Request model for the /query_project endpoint, matching the interface of
    :class:`~selene.tools.query_project_tools.QueryProjectTool`.
    """

    project_name: str
    tool_name: str
    tool_params_json: str


class ProjectServer:
    """
    A lightweight Flask server that exposes a SeleneAgent's project querying
    capabilities via HTTP, using the LSP language server backend for symbolic retrieval.

    Projects are loaded on demand when a query is made for them, and cached in memory for subsequent queries.

    The server instantiates a :class:`SeleneAgent` with default options and
    provides a ``/query_project`` endpoint whose interface matches
    :class:`~selene.tools.query_project_tools.QueryProjectTool`.
    """

    PORT = SelenePorts.PROJECT_SERVER_PORT

    def __init__(self, host: str = "127.0.0.1", port: int | None = None) -> None:
        """
        :param host: the host address to listen on.
        :param port: the port to listen on; if None, use default
        """
        from selene.agent import SeleneAgent

        if port is None:
            port = self.PORT

        selene_config = SeleneConfig.from_config_file().with_headless_mode_overrides()
        selene_config.language_backend = LanguageBackend.LSP

        self._agent = SeleneAgent(selene_config=selene_config)
        self._loaded_projects_by_root: dict[str, "Project"] = {}
        self._project_load_locks_by_root: dict[str, threading.Lock] = {}
        self._active_project_lock = threading.Lock()
        self._loaded_projects_lock = threading.Lock()
        self._port = port
        self._host = host

        # create the Flask application, limiting trusted hosts for the case where the server is running on localhost
        self._app = Flask(__name__)
        local_hosts = ["localhost", "127.0.0.1"]
        if self._host in local_hosts:
            self._app.config["TRUSTED_HOSTS"] = local_hosts

        self._setup_routes()

    def _setup_routes(self) -> None:
        @self._app.route("/heartbeat", methods=["GET"])
        def heartbeat() -> dict[str, str]:
            return {"status": "alive"}

        @self._app.route("/query_project", methods=["POST"])
        def query_project() -> str:
            query_request = QueryProjectRequest.model_validate(request.get_json())
            return self._query_project(query_request)

    def _get_project(self, project_root_or_name: str) -> "Project":
        """Gets the project with the given name, loading it if necessary."""
        selene_config = self._agent.selene_config
        registered_project = selene_config.get_registered_project(project_root_or_name)
        if registered_project is None:
            raise ValueError(f"Project '{project_root_or_name}' is not registered with Selene.")

        key = str(registered_project.project_root)

        # find or publish the per-project load lock while holding the shared dictionaries
        with self._loaded_projects_lock:
            project = self._loaded_projects_by_root.get(key)
            if project is not None:
                return project
            project_load_lock = self._project_load_locks_by_root.get(key)
            if project_load_lock is None:
                project_load_lock = threading.Lock()
                self._project_load_locks_by_root[key] = project_load_lock

        # initialize only this project; another project's cached lookup or cold load can proceed
        with project_load_lock:
            with self._loaded_projects_lock:
                project = self._loaded_projects_by_root.get(key)
                if project is not None:
                    return project

            with LogTime(f"Loading project '{project_root_or_name}'"):
                project = registered_project.get_project_instance(selene_config)
                project.create_language_server_manager()

            with self._loaded_projects_lock:
                self._loaded_projects_by_root[key] = project
            return project

    def _query_project(self, req: QueryProjectRequest) -> str:
        """Handle a /query_project request by invoking the agent on the specified project and tool.

        The active project is process-wide state, whereas ``apply_ex`` runs the tool on the
        agent's task executor thread. Without the lock, a second request entering
        ``active_project_context`` while the first request's tool is still executing would
        redirect that tool to the wrong project (and restore the wrong project afterwards).
        """
        project = self._get_project(req.project_name)
        with self._active_project_lock, self._agent.active_project_context(project):
            tool = self._agent.get_tool_by_name(req.tool_name)
            if not tool.is_readonly():
                raise ValueError(f"Tool '{req.tool_name}' is not read-only and cannot be executed via the query_project route")
            params = json.loads(req.tool_params_json)
            return tool.apply_ex(**params)

    def run(self) -> None:
        """
        Run the server on the given host and port.
        """
        from flask import cli

        # suppress the default Flask startup banner
        # ty cannot model reassigning a third-party module's function attribute (it rejects any
        # replacement, even one with an identical signature), so the monkeypatch is suppressed here
        cli.show_server_banner = lambda *args, **kwargs: None  # ty: ignore[invalid-assignment]

        self._app.run(host=self._host, port=self._port, debug=False, use_reloader=False, threaded=True)


class ProjectServerClient:
    """Client for interacting with a running :class:`ProjectServer`.

    Upon instantiation, the client verifies that the server is reachable
    by sending a heartbeat request. If the server is not running, a
    :class:`ConnectionError` is raised.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = ProjectServer.PORT, timeout: int = 300) -> None:
        """
        :param host: the host address of the project server.
        :param port: the port of the project server.
        :raises ConnectionError: if the project server is not reachable.
        """
        self._session = DirectHttpSession()
        self._base_url = f"http://{host}:{port}"
        self._timeout = timeout

        # verify that the server is running
        try:
            response = self._session.get(f"{self._base_url}/heartbeat", timeout=5)
            response.raise_for_status()
        except requests_lib.ConnectionError:
            raise ConnectionError(f"ProjectServer is not reachable at {self._base_url}. Make sure the server is running.")
        except requests_lib.RequestException as e:
            raise ConnectionError(f"ProjectServer health check failed: {e}")

    def query_project(self, project_name: str, tool_name: str, tool_params_json: str) -> str:
        """
        Query a project by executing a Selene tool in its context.

        The interface matches :meth:`QueryProjectTool.apply
        <selene.tools.query_project_tools.QueryProjectTool.apply>`.

        :param project_name: the name of the project to query.
        :param tool_name: the name of the tool to execute. The tool must be read-only.
        :param tool_params_json: the parameters to pass to the tool, encoded as a JSON string.
        :return: the tool's result as a string.
        """
        payload = QueryProjectRequest(
            project_name=project_name,
            tool_name=tool_name,
            tool_params_json=tool_params_json,
        ).model_dump()

        response = self._session.post(f"{self._base_url}/query_project", json=payload, timeout=self._timeout)
        response.raise_for_status()
        return response.text
