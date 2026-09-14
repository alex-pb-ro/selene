import os
import signal
import subprocess

from pydantic import BaseModel

from selene.util.cancellation import CancellationToken
from solidlsp.util.privacy import SubprocessPrivacy
from solidlsp.util.subprocess_util import subprocess_kwargs, terminate_process_tree_with_kill_fallback


class ShellCommandResult(BaseModel):
    stdout: str
    return_code: int
    cwd: str
    stderr: str | None = None


def execute_shell_command(command: str, cwd: str | None = None, capture_stderr: bool = False) -> ShellCommandResult:
    """
    Execute a shell command and return the output.

    :param command: The command to execute.
    :param cwd: The working directory to execute the command in. If None, the current working directory will be used.
    :param capture_stderr: Whether to capture the stderr output.
    :return: The output of the command.
    """
    if cwd is None:
        cwd = os.getcwd()

    CancellationToken.check_current()
    process = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if capture_stderr else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=SubprocessPrivacy.environment(),
        start_new_session=True,
        **subprocess_kwargs(),
    )

    try:
        while True:
            CancellationToken.check_current()
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        # retain task ownership while stopping the shell and draining its output pipes
        process_group_id = process.pid if os.name == "posix" else None
        terminate_process_tree_with_kill_fallback(process, terminate_timeout=0.25, process_group_id=process_group_id)
        if process_group_id is not None:
            # the shell may exit before descendants that ignore SIGTERM
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # still wait for pipe closure if the OS refuses to signal the group
                pass
        process.communicate()
        raise
    return ShellCommandResult(stdout=stdout, stderr=stderr, return_code=process.returncode, cwd=cwd)


def subprocess_check_output(
    args: list[str], encoding: str = "utf-8", strip: bool = True, timeout: float | None = None, cwd: str | None = None
) -> str:
    output = subprocess.check_output(
        args, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, env=os.environ.copy(), cwd=cwd, **subprocess_kwargs()
    ).decode(encoding)
    if strip:
        output = output.strip()
    return output
