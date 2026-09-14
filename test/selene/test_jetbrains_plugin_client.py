import pytest

from selene.constants import REPO_ROOT
from selene.jetbrains.jetbrains_plugin_client import JetBrainsPluginClient


class TestSeleneJetBrainsPluginClient:
    @pytest.mark.parametrize(
        "selene_path, plugin_path",
        [
            (REPO_ROOT, REPO_ROOT),
            ("/home/user/project", "/home/user/project"),
            ("/home/user/project", "//wsl.localhost/Ubuntu-24.04/home/user/project"),
            ("/home/user/project", "//wsl$/Ubuntu/home/user/project"),
            ("/home/user/project", "//wsl$/Ubuntu/home/user/project"),
            ("/mnt/c/Users/user/projects/my-app", "/workspaces/selene/C:/Users/user/projects/my-app"),
        ],
    )
    def test_path_matching(self, selene_path, plugin_path) -> None:
        assert JetBrainsPluginClient._paths_match(selene_path, plugin_path)
