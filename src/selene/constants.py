from pathlib import Path

_repo_root_path = Path(__file__).parent.parent.parent.resolve()
_selene_pkg_path = Path(__file__).parent.resolve()
_resources_path = _selene_pkg_path / "resources"

SELENE_MANAGED_DIR_NAME = ".selene"

# TODO: Path-related constants should be moved to SelenePaths; don't add further constants here.
REPO_ROOT = str(_repo_root_path)
RESOURCES_DIR = str(_resources_path)
PROMPT_TEMPLATES_DIR_INTERNAL = str(_resources_path / "config" / "prompt_templates")
SELENES_OWN_CONTEXT_YAMLS_DIR = str(_resources_path / "config" / "contexts")
"""The contexts that are shipped with the Selene package, i.e. the default contexts."""
SELENES_OWN_MODE_YAMLS_DIR = str(_resources_path / "config" / "modes")
"""The modes that are shipped with the Selene package, i.e. the default modes."""
INTERNAL_MODE_YAMLS_DIR = str(_resources_path / "config" / "internal_modes")
"""Internal modes, never overridden by user modes."""
SELENE_DASHBOARD_DIR = str(_resources_path / "dashboard")
SELENE_ICON_DIR = str(_resources_path / "icons")

DEFAULT_SOURCE_FILE_ENCODING = "utf-8"
"""The default encoding assumed for project source files."""
DEFAULT_CONTEXT = "desktop-app"

SELENE_FILE_ENCODING = "utf-8"
"""The encoding used for Selene's own files, such as configuration files and memories."""

PROJECT_TEMPLATE_FILE = str(_resources_path / "project.template.yml")
PROJECT_LOCAL_TEMPLATE_FILE = str(_resources_path / "project.local.template.yml")
SELENE_CONFIG_TEMPLATE_FILE = str(_resources_path / "selene_config.template.yml")

SELENE_LOG_FORMAT = "%(levelname)-5s %(asctime)-15s [%(threadName)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"

LOG_MESSAGES_BUFFER_SIZE = 2500
"""The maximum number of log messages to keep in the buffer (for the dashboard)."""


class SelenePorts:
    TRAY_MANAGER_PORT = 0x5FA0
    PROJECT_SERVER_PORT = 0x5FA1
    JETBRAINS_PLUGIN_SERVER_BASE_PORT = 0x5EA2
    DASHBOARD_API_BASE_PORT = 0x5FDA
