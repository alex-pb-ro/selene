"""Verify the isolated stdio image with a synthetic project shared by the local daemon."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class IsolatedMCPProbe:
    _IMAGE_SOURCES = (
        "src/selene/isolation/linux_network.py", "src/selene/isolation/bootstrap.py",
        "src/selene/config/selene_config.py", "src/selene/ls_manager.py", "src/selene/project.py",
        "src/solidlsp/ls.py", "src/solidlsp/settings.py", "containers/isolated/entrypoint.py", "LICENSE",
        "src/selene/indexing/local_index.py", "src/selene/indexing/inotify.py", "src/selene/indexing/scope.py",
        "src/selene/indexing/coverage.py", "src/selene/indexing/journal.py", "src/selene/indexing/kqueue.py",
        "src/selene/indexing/project_policy.py", "src/selene/indexing/__init__.py",
        "src/selene/util/file_snapshot.py", "src/selene/util/file_system.py", "src/selene/code_editor.py",
        "src/selene/tools/index_tools.py", "src/selene/tools/file_tools.py", "src/selene/tools/__init__.py",
        "src/selene/context/__init__.py", "src/selene/context/model.py", "src/selene/context/sources.py",
        "src/selene/context/semantic.py", "src/selene/context/selection.py", "src/selene/context/bundles.py",
        "src/selene/tools/context_tools.py",
        "src/selene/context/python_bindings.py", "src/selene/util/json_budget.py",
        "src/selene/changes/__init__.py", "src/selene/changes/model.py", "src/selene/changes/resolver.py", "src/selene/changes/unified_diff.py",
        "src/selene/impact/__init__.py", "src/selene/impact/model.py", "src/selene/impact/graph.py", "src/selene/impact/adapters.py", "src/selene/impact/service.py",
        "src/selene/tools/impact_tools.py",
        "src/selene/edit_plans/__init__.py", "src/selene/edit_plans/model.py", "src/selene/edit_plans/filesystem.py",
        "src/selene/edit_plans/journal.py", "src/selene/edit_plans/execution.py", "src/selene/edit_plans/service.py",
        "src/selene/tools/change_plan_tools.py",
        "src/selene/memories/evidence.py", "src/selene/memories/project_evidence.py",
        "src/selene/memories/memory_manager.py", "src/selene/memories/memory_reference_analysis.py",
        "src/selene/tools/memory_tools.py", "src/selene/dashboard.py", "src/selene/mcp.py",
        "src/selene/resources/dashboard/dashboard.js", "src/selene/resources/dashboard/index.html",
        "src/selene/resources/config/modes/no-memories.yml",
    )

    def __init__(self, fixture_root: Path, docker_socket: Path, image: str):
        self.root = Path(__file__).resolve().parents[2]
        self.fixture_root = fixture_root.resolve(strict=True)
        self.socket = docker_socket
        self.image = image

    @staticmethod
    def _text(result) -> str:
        return "\n".join(item.text for item in result.content if item.type == "text")

    @staticmethod
    def _python(source: str) -> str:
        return "python -c " + shlex.quote(source)

    def _daemon_logs(self, project: Path, approved: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="selene-probe-docker-") as configuration:
            environment = {"PATH": os.environ["PATH"], "DOCKER_CONFIG": configuration}
            command = ["docker", "--host", "unix://" + str(self.socket)]
            ids = subprocess.check_output(
                [*command, "ps", "--filter", "ancestor=" + self.image, "--format={{.ID}}"], env=environment, text=True,
            ).split()
            matches = []
            for container_id in ids:
                inspected = json.loads(subprocess.check_output([*command, "inspect", container_id], env=environment, text=True))[0]
                if any(mount.get("Source") == str(project) and mount["Destination"] == "/workspace" for mount in inspected["Mounts"]):
                    matches.append(inspected)
            assert len(matches) == 1, "Expected one container for the synthetic project"
            inspected = matches[0]
            logs = subprocess.run([*command, "logs", inspected["Id"]], env=environment, capture_output=True, text=True)
            assert approved not in logs.stdout and approved not in logs.stderr
            return {
                "source_canary_absent_from_daemon_logs": True,
                "docker_logging_driver": inspected["HostConfig"]["LogConfig"]["Type"],
                "docker_network_mode": inspected["HostConfig"]["NetworkMode"],
            }

    async def run(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="mcp-", dir=self.fixture_root) as directory:
            base = Path(directory)
            project = base / "project"
            project.mkdir()
            approved = "APPROVED_CLIENT_CANARY"
            outside = "OUTSIDE_WORKSPACE_CANARY"
            memory_canary = "EXPLICIT_DECISION_CANARY"
            (project / "module.py").write_text(f'def visible_symbol():\n    return "{approved}"\n')
            (base / "outside.txt").write_text(outside)
            (project / "escape.txt").symlink_to("../outside.txt")
            stderr_path = self.fixture_root / "last-client-stderr.log"
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    str(self.root / "scripts/run_isolated.py"),
                    "--project", str(project), "--docker-socket", str(self.socket), "--image", self.image,
                ],
                env={**os.environ, "SELENE_SYNTHETIC_PARENT_SECRET": "parent-only-canary"},
            )
            observations = {}
            with stderr_path.open("w") as stderr:
                async with stdio_client(parameters, errlog=stderr) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        observations["server_name"] = initialized.serverInfo.name
                        catalog = await session.list_tools()
                        observations["tool_count"] = len(catalog.tools)

                        source = await session.call_tool("read_file", {"relative_path": "module.py"})
                        assert not source.isError and approved in self._text(source), self._text(source)
                        observations["source_returned_to_connected_client"] = True

                        symbols = await session.call_tool("find_symbol", {
                            "name_path_pattern": "visible_symbol", "relative_path": "module.py", "include_body": True,
                        })
                        assert not symbols.isError and "visible_symbol" in self._text(symbols), self._text(symbols)
                        assert approved in self._text(symbols), self._text(symbols)
                        observations["local_pyright_symbol_body_returned"] = True

                        indexed = await session.call_tool("search_index", {"query": "APPROVED_CLIENT_CANARY"})
                        assert not indexed.isError and approved in self._text(indexed), self._text(indexed)
                        observations["index_search_returns_versioned_source"] = bool(json.loads(self._text(indexed))["matches"][0]["sha256"])

                        # exercise nested anchors, exact budgets, body handles and stable continuation pages over actual MCP
                        for number in range(6):
                            (project / f"support_{number}.py").write_text(f"from module import visible_symbol\n\ndef support_{number}():\n    return visible_symbol()\n")
                        bundled = await session.call_tool("find_context", {
                            "query": "visible_symbol", "anchors": [{"path": "module.py", "symbol": "visible_symbol"}],
                            "max_chars": 5000, "include_bodies": False,
                        })
                        assert not bundled.isError, self._text(bundled)
                        page = json.loads(self._text(bundled))
                        assert page["budget"]["used"] == len(self._text(bundled)) <= 5000
                        assert page["continuation"] and page["items"][0]["source"]["path"] == "module.py", page
                        selected = await session.call_tool("read_context_items", {"bundle_id": page["bundle_id"], "item_ids": [page["items"][0]["id"]]})
                        assert not selected.isError and approved in self._text(selected), self._text(selected)
                        continued = await session.call_tool("continue_context", {"continuation": page["continuation"], "max_chars": 5000})
                        assert not continued.isError, self._text(continued)
                        next_page = json.loads(self._text(continued))
                        assert {item["id"] for item in page["items"]}.isdisjoint(item["id"] for item in next_page["items"])
                        observations["context_nested_anchors_budgets_bodies_and_continuations"] = True

                        # analyze a proposed API change while preserving its on-disk source
                        original = (project / "module.py").read_bytes()
                        proposal = {"path": "module.py", "expected_sha256": hashlib.sha256(original).hexdigest(), "new_content": original.decode().replace("visible_symbol()", "visible_symbol(required)")}
                        impact = await session.call_tool("analyze_change", {"changes": [proposal], "max_chars": 20000})
                        assert not impact.isError, self._text(impact)
                        impact_report = json.loads(self._text(impact))
                        assert impact_report["budget"]["used"] == len(self._text(impact)) <= 20000
                        assert any(finding["target"]["path"].startswith("support_") for finding in impact_report["language_server_relationships"]), impact_report
                        assert (project / "module.py").read_bytes() == original
                        rejected = await session.call_tool("analyze_change", {"changes": [{**proposal, "expected_sha256": "0" * 64}]})
                        assert rejected.isError and "ChangeConflict" in self._text(rejected), self._text(rejected)
                        observations["impact_analyzes_unapplied_change_and_rejects_wrong_source_hash"] = True

                        # bind an explicitly authored decision to current local source evidence
                        provenance = {"owner": "team:synthetic", "scope": "module.py", "origin": "decision", "evidence": [
                            {"path": "module.py", "sha256": hashlib.sha256(original).hexdigest(), "start_line": 1, "end_line": 2},
                        ]}
                        recorded = await session.call_tool("write_memory", {
                            "memory_name": "architecture/api", "content": "Prefer explicit API inputs. " + memory_canary, "provenance": provenance,
                        })
                        assert not recorded.isError, self._text(recorded)
                        checked = await session.call_tool("check_memory", {"memory_name": "architecture/api"})
                        assert not checked.isError, self._text(checked)
                        memory_status = json.loads(self._text(checked))
                        assert memory_status["status"] == "current", memory_status
                        memory_path = project / ".selene" / "memories" / "architecture" / "api.md"
                        assert memory_path.stat().st_mode & 0o777 == 0o600
                        assert approved not in memory_path.read_text()
                        edited = await session.call_tool("edit_memory", {
                            "memory_name": "architecture/api", "needle": "explicit", "repl": "documented", "mode": "literal",
                        })
                        assert not edited.isError, self._text(edited)
                        review_needed = await session.call_tool("check_memory", {"memory_name": "architecture/api"})
                        edited_status = json.loads(self._text(review_needed))
                        assert edited_status["status"] == "needs_review", edited_status
                        stale_review = await session.call_tool("review_memory", {
                            "memory_name": "architecture/api", "provenance": provenance, "expected_memory_sha256": memory_status["memory_sha256"],
                        })
                        assert stale_review.isError and "version conflict" in self._text(stale_review), self._text(stale_review)
                        reviewed = await session.call_tool("review_memory", {
                            "memory_name": "architecture/api", "provenance": provenance, "expected_memory_sha256": edited_status["memory_sha256"],
                        })
                        assert not reviewed.isError and json.loads(self._text(reviewed))["status"] == "current", self._text(reviewed)
                        observations["memory_records_versions_and_requires_review_after_body_edits"] = True

                        (project / "host_created.py").write_text("hostindexcanary = 1\n")
                        stale = await session.call_tool("read_context_items", {"bundle_id": page["bundle_id"], "item_ids": [page["items"][0]["id"]]})
                        assert stale.isError and "StaleContextError" in self._text(stale), self._text(stale)
                        observations["context_rejects_changed_index_generation"] = True
                        host_indexed = await session.call_tool("search_index", {"query": "hostindexcanary"})
                        assert not host_indexed.isError, self._text(host_indexed)
                        assert [match["path"] for match in json.loads(self._text(host_indexed))["matches"]] == ["host_created.py"], self._text(host_indexed)
                        observations["host_shared_filesystem_edit_is_indexed_immediately"] = True
                        observations["index_watcher"] = json.loads(self._text(host_indexed))["status"]["watcher"]

                        network = await session.call_tool("execute_shell_command", {
                            "command": self._python("import socket; socket.socket(socket.AF_INET)"),
                        })
                        network_output = json.loads(self._text(network))
                        assert network_output["return_code"] != 0 and "PermissionError" in network_output["stderr"], network_output
                        observations["managed_shell_network_denied"] = True

                        escape = await session.call_tool("read_file", {"relative_path": "escape.txt"})
                        assert outside not in self._text(escape)
                        assert "Error" in self._text(escape) or escape.isError, self._text(escape)
                        observations["outside_project_symlink_cannot_read_host_canary"] = True

                        inspect = await session.call_tool("execute_shell_command", {"command": self._python(
                            "import json,os; print(json.dumps({'uid':os.getuid(), 'secret_present': "
                            "'SELENE_SYNTHETIC_PARENT_SECRET' in os.environ, 'status':open('/proc/self/status').read()}))"
                        )})
                        inspect_output = json.loads(json.loads(self._text(inspect))["stdout"])
                        assert inspect_output["uid"] != 0 and not inspect_output["secret_present"]
                        assert "NoNewPrivs:\t1" in inspect_output["status"] and "Seccomp:\t2" in inspect_output["status"]
                        observations["shell_has_no_parent_secret_and_keeps_kernel_restrictions"] = True

                        created = await session.call_tool("create_text_file", {"relative_path": "created.py", "content": "value = 42\n"})
                        assert not created.isError and (project / "created.py").read_text() == "value = 42\n", self._text(created)
                        observations["authorized_project_edit_visible_on_host"] = True
                        # exercise durable nested proposals and idempotent apply through the actual MCP schema
                        planned_contents = original.decode().replace("visible_symbol()", "visible_symbol(required)")
                        plan_args = {"request_id": "isolated-recovery", "changes": [
                            {"path": "module.py", "expected_sha256": hashlib.sha256(original).hexdigest(), "new_content": planned_contents},
                            {"path": "planned.py", "expected_sha256": None, "new_content": "planned = True\n"},
                        ]}
                        prepared = await session.call_tool("prepare_change", plan_args)
                        assert not prepared.isError, self._text(prepared)
                        plan_report = json.loads(self._text(prepared))
                        assert plan_report["status"] == "prepared", plan_report
                        assert (project / "module.py").read_bytes() == original
                        plan_id = plan_report["plan_id"]
                        applied = await session.call_tool("apply_change", {"plan_id": plan_id})
                        assert not applied.isError and json.loads(self._text(applied))["status"] == "applied", self._text(applied)
                        assert (project / "module.py").read_text() == planned_contents
                        assert (project / "planned.py").read_text() == "planned = True\n"
                        repeated = await session.call_tool("prepare_change", plan_args)
                        assert not repeated.isError and json.loads(self._text(repeated))["plan_id"] == plan_id, self._text(repeated)
                        applied_again = await session.call_tool("apply_change", {"plan_id": plan_id})
                        assert not applied_again.isError and json.loads(self._text(applied_again))["status"] == "applied", self._text(applied_again)
                        observations["prepared_changes_preserve_source_and_apply_idempotently"] = True
                        changed_memory = await session.call_tool("check_memory", {"memory_name": "architecture/api"})
                        assert not changed_memory.isError, self._text(changed_memory)
                        changed_memory_status = json.loads(self._text(changed_memory))
                        assert changed_memory_status["status"] == "stale", changed_memory_status
                        warned = await session.call_tool("read_memory", {"memory_name": "architecture/api"})
                        assert not warned.isError and '"status": "stale"' in self._text(warned) and memory_canary in self._text(warned), self._text(warned)
                        updated_provenance = {**provenance, "evidence": [
                            {"path": "module.py", "sha256": hashlib.sha256(planned_contents.encode()).hexdigest(), "start_line": 1, "end_line": 2},
                        ]}
                        reviewed_change = await session.call_tool("review_memory", {
                            "memory_name": "architecture/api", "provenance": updated_provenance,
                            "expected_memory_sha256": changed_memory_status["memory_sha256"],
                        })
                        assert not reviewed_change.isError and json.loads(self._text(reviewed_change))["status"] == "current", self._text(reviewed_change)
                        observations["memory_flags_source_changes_and_accepts_explicit_current_evidence"] = True
                        observations["decision_canary_absent_from_daemon_logs"] = self._daemon_logs(project, memory_canary)["source_canary_absent_from_daemon_logs"]

                        observations.update(self._daemon_logs(project, approved))

                        image_paths = {
                            path: "/opt/selene/container_entrypoint.py" if path == "containers/isolated/entrypoint.py" else "/opt/selene/" + path
                            for path in self._IMAGE_SOURCES
                        }
                        hashes = await session.call_tool("execute_shell_command", {"command": self._python(
                            "import hashlib,json,pathlib; paths=" + repr(image_paths) + "; "
                            "print(json.dumps({p:hashlib.sha256(pathlib.Path(q).read_bytes()).hexdigest() for p,q in paths.items()}))"
                        )})
                        actual_hashes = json.loads(json.loads(self._text(hashes))["stdout"])
                        expected_hashes = {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in image_paths}
                        assert actual_hashes == expected_hashes
                        observations["tested_image_sources_match_checkout"] = True

            # start a new container to verify that project identity and retained file operations survive restart
            with stderr_path.open("a") as stderr:
                async with stdio_client(parameters, errlog=stderr) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        recovered = await session.call_tool("recover_change", {"plan_id": plan_id, "action": "rollback"})
                        assert not recovered.isError, self._text(recovered)
                        recovery = json.loads(self._text(recovered))
                        assert recovery["status"] == "rolled_back", recovery
                        assert (project / "module.py").read_bytes() == original
                        assert not (project / "planned.py").exists()
                        observations["prepared_changes_roll_back_across_container_restart"] = True
                        restarted_check = await session.call_tool("check_memory", {"memory_name": "architecture/api"})
                        assert not restarted_check.isError, self._text(restarted_check)
                        restarted_status = json.loads(self._text(restarted_check))
                        assert restarted_status["status"] == "stale", restarted_status
                        rereviewed = await session.call_tool("review_memory", {
                            "memory_name": "architecture/api", "provenance": provenance,
                            "expected_memory_sha256": restarted_status["memory_sha256"],
                        })
                        assert not rereviewed.isError and json.loads(self._text(rereviewed))["status"] == "current", self._text(rereviewed)
                        observations["memory_scope_and_evidence_checks_survive_container_restart"] = True


            captured = stderr_path.read_text()
            assert approved not in captured and outside not in captured and memory_canary not in captured, captured
            observations["source_canaries_absent_from_client_stderr"] = True
            metadata = [path for path in (project / ".selene").rglob("*") if path.is_file()]
            retained = [p for p in metadata if approved.encode() in p.read_bytes()]
            journals = project / ".selene" / "change-plans"
            assert retained and all(p.is_relative_to(journals) for p in retained)
            assert journals.stat().st_mode & 0o777 == 0o700
            assert (journals / ".gitignore").read_text() == "*\n"
            observations["source_canary_retained_only_in_explicit_private_change_journal"] = True
            decision_copies = [p for p in metadata if memory_canary.encode() in p.read_bytes()]
            assert decision_copies == [memory_path], decision_copies
            observations["decision_retained_only_in_explicit_private_memory"] = True
            return {
                "observations": observations,
                "method": {
                    "image": self.image,
                    "synthetic_only": True,
                    "model_calls": 0,
                    "source_sha256": {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in (
                        *self._IMAGE_SOURCES, "scripts/run_isolated.py", "scripts/build_isolated.py", "containers/isolated/Dockerfile", "security/probes/isolated_mcp.py",
                    )},
                    "scope": "Real stdio MCP, cached local Pyright and managed shell in the isolated Linux image. "
                    "Host fixtures are synthetic; this is not a provider-contract audit or a full packet capture.",
                },
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(IsolatedMCPProbe(args.fixture_root, args.docker_socket, args.image).run())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
