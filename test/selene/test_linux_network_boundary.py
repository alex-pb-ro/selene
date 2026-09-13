"""Optional real-kernel verification using a separately provisioned local Docker daemon."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("SELENE_TEST_DOCKER_SOCKET"), reason="Requires an explicit local Docker test daemon and cached image"
)
def test_network_boundary_preserves_stdio_and_event_loop_but_blocks_outside_receivers(tmp_path):
    output = tmp_path / "network-results.json"
    probe = Path(__file__).resolve().parents[2] / "security/probes/linux_network_boundary.py"
    subprocess.run(
        [sys.executable, str(probe), "--docker-socket", os.environ["SELENE_TEST_DOCKER_SOCKET"], "--output", str(output)],
        check=True,
        timeout=60,
    )
    results = json.loads(output.read_text())["observations"]
    assert results["control_received_but_filtered_payload_not_received"]
    assert results["exec_child_inherits_denial"]
    assert results["event_loop_thread_wakeup_works"]


@pytest.mark.skipif(
    not all(os.environ.get(key) for key in ("SELENE_TEST_DOCKER_SOCKET", "SELENE_TEST_DOCKER_IMAGE_ID", "SELENE_TEST_DOCKER_FIXTURE_ROOT")),
    reason="Requires the isolated image and a synthetic fixture directory shared with the local Docker daemon",
)
def test_isolated_mcp_returns_authorized_content_without_network_or_source_retention(tmp_path):
    output = tmp_path / "isolated-mcp-results.json"
    probe = Path(__file__).resolve().parents[2] / "security/probes/isolated_mcp.py"
    subprocess.run(
        [
            sys.executable,
            str(probe),
            "--fixture-root",
            os.environ["SELENE_TEST_DOCKER_FIXTURE_ROOT"],
            "--docker-socket",
            os.environ["SELENE_TEST_DOCKER_SOCKET"],
            "--image",
            os.environ["SELENE_TEST_DOCKER_IMAGE_ID"],
            "--output",
            str(output),
        ],
        check=True,
        timeout=60,
    )
    results = json.loads(output.read_text())["observations"]
    assert results["authorized_project_edit_visible_on_host"]
    assert results["local_pyright_symbol_body_returned"]
    assert results["managed_shell_network_denied"]
    assert results["source_canary_not_retained_in_project_metadata"]
