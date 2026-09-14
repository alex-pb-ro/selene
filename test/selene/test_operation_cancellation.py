import os
import signal
import sys
import time
from concurrent.futures import CancelledError
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from selene.code_editor import LanguageServerCodeEditor
from selene.task_executor import TaskExecutor
from selene.tools.tools_base import Tool, ToolCallError, ToolMarkerCanEdit, ToolMarkerDoesNotRequireActiveProject, ToolMarkerSymbolicRead
from selene.util.shell import execute_shell_command
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_exceptions import SolidLSPException
from solidlsp.ls_process import LanguageServerTerminatedException
from solidlsp.util.subprocess_util import convert_shell_cmd


@pytest.mark.parametrize("cancelled", [False, True])
def test_late_workspace_rename_respects_cancellation(tmp_path, cancelled):
    # pause a rename response at the language server boundary
    old_path, new_path = tmp_path / "Old.java", tmp_path / "New.java"
    source = "class Old {}\n"
    old_path.write_text(source)
    entered, release = Event(), Event()

    def rename_response(**kwargs):
        entered.set()
        assert release.wait(3)
        return {"documentChanges": [{"kind": "rename", "oldUri": old_path.as_uri(), "newUri": new_path.as_uri()}]}

    retriever = Mock()
    retriever.project = SimpleNamespace(
        project_root=str(tmp_path),
        project_config=SimpleNamespace(encoding="utf-8"),
        line_ending=SimpleNamespace(newline_str="\n"),
    )
    retriever.find_unique.return_value = SimpleNamespace(location=SimpleNamespace(has_position_in_file=lambda: True, line=0, column=6))
    retriever.get_language_server.return_value.request_rename_symbol_edit.side_effect = rename_response
    editor = LanguageServerCodeEditor(retriever)
    executor = TaskExecutor("WorkspaceRenameCancellationExecutor")
    task = executor.issue_task(lambda: editor.rename_symbol("Old", "Old.java", "New"))
    try:
        # release the response after the caller has optionally cancelled
        assert entered.wait(2)
        if cancelled:
            task.cancel()
        release.set()
        executor.execute_task(lambda: None, timeout=3)

        # observe the completed operation through its result and filesystem effects
        if cancelled:
            with pytest.raises(CancelledError):
                task.result(timeout=1)
            assert old_path.read_text() == source
            assert not new_path.exists()
        else:
            assert "Successfully renamed" in task.result(timeout=1)
            assert new_path.read_text() == source
            assert not old_path.exists()
    finally:
        release.set()
        executor.shutdown()


@pytest.mark.parametrize("mutating", [True, False])
def test_language_server_failure_does_not_repeat_uncertain_mutation(tmp_path, mutating):
    executor = TaskExecutor("RetryPolicyExecutor")
    attempts = []
    target = tmp_path / "changes.txt"
    agent = Mock()
    agent.selene_config = SimpleNamespace(tool_timeout=1)
    agent.issue_task.side_effect = executor.issue_task
    agent.tool_is_active.return_value = True
    agent.get_language_server_manager.return_value = None

    class ReadTool(Tool, ToolMarkerSymbolicRead, ToolMarkerDoesNotRequireActiveProject):
        def apply(self) -> str:
            """Simulate a request that loses its language server."""
            attempts.append("invoked")
            if self.can_edit():
                target.write_text(str(len(attempts)))
            if len(attempts) == 1:
                raise SolidLSPException("Lost response", cause=LanguageServerTerminatedException("Stopped", LanguageServerId.PYTHON))
            return "recovered"

    class EditTool(ReadTool, ToolMarkerCanEdit):
        pass

    tool = (EditTool if mutating else ReadTool)(agent)
    if mutating:
        with pytest.raises(ToolCallError, match="effects may be partial"):
            tool.apply_ex(log_call=False, catch_exceptions=False)
        assert target.read_text() == "1"
    else:
        assert tool.apply_ex(log_call=False, catch_exceptions=False) == "recovered"
        assert len(attempts) == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell process-group cancellation")
def test_cancelled_shell_stops_stubborn_descendant_before_next_task(tmp_path):
    executor = TaskExecutor("ShellCancellationExecutor")
    pid_path = tmp_path / "child.pid"
    code = (
        "import os, signal, time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    command = convert_shell_cmd([sys.executable, "-c", code]) + " & wait"
    task = executor.issue_task(lambda: execute_shell_command(command, cwd=str(tmp_path)))
    child = None
    try:
        deadline = time.monotonic() + 3
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        child = psutil.Process(int(pid_path.read_text()))
        task.cancel()
        with pytest.raises(CancelledError):
            task.result(timeout=1)
        assert executor.execute_task(lambda: "next task", timeout=4) == "next task"
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    finally:
        task.cancel()
        if child is not None:
            try:
                child.send_signal(signal.SIGKILL)
            except psutil.NoSuchProcess:
                pass
