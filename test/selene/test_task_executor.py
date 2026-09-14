from concurrent.futures import CancelledError
from threading import Event

import pytest

from selene.task_executor import TaskExecutor
from selene.util.cancellation import CancellationToken
from selene.util.file_system import write_file_atomic


@pytest.fixture
def executor():
    executor = TaskExecutor("TestExecutor")
    yield executor
    assert executor.shutdown(timeout=3)


def test_task_executor_sequence(executor):
    started, release = Event(), Event()
    effects = []

    def first():
        started.set()
        assert release.wait(3)
        effects.append("first")

    first_task = executor.issue_task(first)
    try:
        assert started.wait(1)
        second = executor.issue_task(lambda: effects.append("second"))
        with pytest.raises(TimeoutError):
            second.result(timeout=0.03, cancel_on_timeout=False)
    finally:
        release.set()
    first_task.result(timeout=1)
    second.result(timeout=1)
    assert effects == ["first", "second"]


@pytest.mark.parametrize("error_type", [ValueError, SystemExit])
def test_task_executor_exception(executor, error_type):
    def fail():
        raise error_type("Task failed")

    failed = executor.issue_task(fail)
    following = executor.issue_task(lambda: 42)
    with pytest.raises(error_type, match="Task failed"):
        failed.result(timeout=1)
    assert following.result(timeout=1) == 42


@pytest.mark.parametrize("cancel_via", ["task", "task_info", "future"])
def test_task_executor_cancel_current_retains_ownership(executor, cancel_via):
    started, release, finished = Event(), Event(), Event()

    def operation():
        started.set()
        assert release.wait(3)
        finished.set()

    task = executor.issue_task(operation)
    try:
        assert started.wait(1)
        following = executor.issue_task(finished.is_set)
        info = executor.get_current_tasks()[0]
        {"task": task, "task_info": info, "future": task.future}[cancel_via].cancel()
        with pytest.raises(CancelledError):
            task.result(timeout=1)
        with pytest.raises(TimeoutError):
            following.result(timeout=0.03, cancel_on_timeout=False)
        current = executor.get_current_tasks()[0]
        assert current.task_id == info.task_id
        assert current.is_running
    finally:
        release.set()
    assert following.result(timeout=1) is True


@pytest.mark.parametrize("task_deadline", [True, False])
def test_task_executor_timeout_retains_ownership(executor, task_deadline):
    started, release, finished = Event(), Event(), Event()

    def operation():
        started.set()
        assert release.wait(3)
        finished.set()

    task = executor.issue_task(operation, timeout=0.05 if task_deadline else None)
    try:
        assert started.wait(1)
        following = executor.issue_task(finished.is_set)
        with pytest.raises(TimeoutError):
            task.result(timeout=1 if task_deadline else 0.02)
        with pytest.raises(TimeoutError):
            following.result(timeout=0.03, cancel_on_timeout=False)
    finally:
        release.set()
    assert following.result(timeout=1) is True


@pytest.mark.parametrize("expire", [False, True])
def test_task_executor_cancellation_before_start(executor, expire):
    started, release, invoked = Event(), Event(), Event()

    def hold():
        started.set()
        assert release.wait(3)

    first = executor.issue_task(hold)
    try:
        assert started.wait(1)
        cancelled = executor.issue_task(invoked.set, timeout=0 if expire else None)
        if not expire:
            cancelled.cancel()
    finally:
        release.set()
    first.result(timeout=1)
    with pytest.raises(TimeoutError if expire else CancelledError):
        cancelled.result(timeout=1)
    assert executor.execute_task(lambda: invoked.is_set(), timeout=1) is False


def test_task_executor_callback_waits_for_actual_completion():
    started, release, callback = Event(), Event(), Event()
    executor = TaskExecutor("CallbackExecutor", callback.set)

    def hold():
        started.set()
        assert release.wait(3)

    task = executor.issue_task(hold)
    try:
        assert started.wait(1)
        task.cancel()
        assert not callback.wait(0.03)
    finally:
        release.set()
    assert callback.wait(1)


def test_task_executor_cancelled_write_preserves_original(executor, tmp_path):
    started, release = Event(), Event()
    target = tmp_path / "decision.md"
    target.write_text("original")

    def write():
        started.set()
        assert release.wait(3)
        write_file_atomic(str(target), "replacement", encoding="utf-8")

    task = executor.issue_task(write)
    try:
        assert started.wait(1)
        task.cancel()
    finally:
        release.set()
    assert executor.execute_task(target.read_text, timeout=1) == "original"
    assert list(tmp_path.iterdir()) == [target]


def test_task_executor_inherits_request_cancellation(executor):
    started, release, checkpoint_passed = Event(), Event(), Event()
    request = CancellationToken()

    def operation():
        started.set()
        assert release.wait(3)
        CancellationToken.check_current()
        checkpoint_passed.set()

    with request.bind():
        task = executor.issue_task(operation)
    try:
        assert started.wait(1)
        request.cancel()
    finally:
        release.set()
    with pytest.raises(CancelledError):
        task.result(timeout=1)
    assert executor.execute_task(checkpoint_passed.is_set, timeout=1) is False


def test_task_executor_request_cancellation_releases_queued_waiter(executor):
    started, release, invoked = Event(), Event(), Event()

    def hold():
        started.set()
        assert release.wait(3)

    first = executor.issue_task(hold)
    request = CancellationToken()
    try:
        assert started.wait(1)
        with request.bind():
            queued = executor.issue_task(invoked.set)
        request.cancel()
        with pytest.raises(CancelledError):
            queued.result(timeout=0.1)
    finally:
        release.set()
    first.result(timeout=1)
    assert executor.execute_task(invoked.is_set, timeout=1) is False


def test_task_executor_shutdown_is_closed_until_running_operation_exits(executor):
    started, release, invoked = Event(), Event(), Event()

    def hold():
        started.set()
        assert release.wait(3)

    executor.issue_task(hold)
    try:
        assert started.wait(1)
        queued = executor.issue_task(invoked.set)
        assert executor.shutdown(timeout=0.01) is False
        with pytest.raises(CancelledError):
            queued.result(timeout=1)
        with pytest.raises(RuntimeError, match="shut down"):
            executor.issue_task(invoked.set)
    finally:
        release.set()
    assert executor.shutdown(timeout=1)
    assert not invoked.is_set()


def test_task_executor_shutdown_from_own_task_does_not_deadlock(executor):
    shutdown_results = []
    task = executor.issue_task(lambda: shutdown_results.append(executor.shutdown(timeout=1)))
    with pytest.raises(CancelledError):
        task.result(timeout=1)
    assert executor.shutdown(timeout=1)
    assert shutdown_results == [False]
