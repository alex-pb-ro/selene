import concurrent.futures
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Thread
from typing import Generic, TypeVar

from sensai.util import logging
from sensai.util.logging import LogTime
from sensai.util.string import ToStringMixin

from selene.util.cancellation import CancellationToken

log = logging.getLogger(__name__)
T = TypeVar("T")


class TaskExecutor:
    def __init__(self, name: str, task_completion_callback: Callable[[], None] | None = None):
        """
        :param name: the name of the task executor, used for logging purposes
        :param task_completion_callback: an optional callback function that will be called after each task completion
            (regardless of success, failure, or cancellation)
        """
        self._task_executor_lock = threading.Condition()
        self._task_executor_queue: deque[TaskExecutor.Task] = deque()
        self._task_executor_task_index = 1
        self._task_executor_current_task: TaskExecutor.Task | None = None
        self._task_executor_last_executed_task_info: TaskExecutor.TaskInfo | None = None
        self._task_completion_callback = task_completion_callback
        self._closed = False
        self._task_executor_thread = Thread(target=self._process_task_queue, name=name, daemon=True)
        self._task_executor_thread.start()

    class Task(ToStringMixin, Generic[T]):
        def __init__(self, function: Callable[[], T], name: str, logged: bool = True, timeout: float | None = None):
            """
            :param function: the function representing the task to execute
            :param name: the name of the task
            :param logged: whether to log management of the task; if False, only errors will be logged
            :param timeout: the maximum time to wait for task completion in seconds, or None to wait indefinitely
            """
            self.name = name
            self.future: concurrent.futures.Future = concurrent.futures.Future()
            self.logged = logged
            self.timeout = timeout
            self._function = function
            self._cancellation = CancellationToken(timeout, on_cancel=self._cancel_result)
            self._execution_finished = threading.Event()
            self._execution_thread: Thread | None = None
            self.future.add_done_callback(self._on_result_completed)

        def _cancel_result(self) -> None:
            self.future.cancel()

        def _on_result_completed(self, future: Future) -> None:
            if future.cancelled():
                self._cancellation.cancel()

        def _set_exception(self, error: BaseException) -> None:
            try:
                self.future.set_exception(error)
            except concurrent.futures.InvalidStateError:
                # retain a result already delivered by cancellation or deadline expiry
                pass

        def _tostring_includes(self) -> list[str]:
            return ["name"]

        def start(self) -> None:
            """
            Executes the task in a separate thread, setting the result or exception on the future.
            """

            def run_task() -> None:
                try:
                    if self.future.done():
                        if self.logged:
                            log.info(f"Task {self.name} was already completed/cancelled; skipping execution")
                        return
                    with self._cancellation.bind(), LogTime(self.name, logger=log, enabled=self.logged):
                        self._cancellation.check()
                        result = self._function()
                        self._cancellation.check()
                        try:
                            self.future.set_result(result)
                        except concurrent.futures.InvalidStateError:
                            # cancellation may race with publishing the completed result
                            pass
                except BaseException as e:
                    if not self.future.done():
                        if not isinstance(e, concurrent.futures.CancelledError | TimeoutError):
                            log.error(f"Error during execution of {self.name}: {e}", exc_info=e)
                        self._set_exception(e)
                finally:
                    self._execution_finished.set()

            self._execution_thread = Thread(target=run_task, name=self.name)
            try:
                self._execution_thread.start()
            except BaseException as e:
                self._set_exception(e)
                self._execution_finished.set()

        def is_current_thread(self) -> bool:
            """Return whether the caller is executing this task."""
            return self._execution_thread is threading.current_thread()

        def is_done(self) -> bool:
            """
            :return: whether the result has settled; a cancelled operation may still be exiting
            """
            return self.future.done()

        def result(self, timeout: float | None = None, cancel_on_timeout: bool = True) -> T:
            """
            Blocks until the task is done or the timeout is reached, and returns the result.
            If an exception occurred during task execution, it is raised here.
            If the timeout is reached, a TimeoutError is raised.
            If the task is cancelled, a CancelledError is raised.

            :param timeout: the caller's maximum wait in seconds; the task's deadline also applies
            :param cancel_on_timeout: whether to cancel the task if the timeout is reached.
                If the task has not yet started, cancellation prevents its execution entirely;
                if it is already running, cancellation is cooperative and its result is discarded.
                The executor waits for the underlying operation to exit before starting subsequent work.
            :return: the result of the task
            """
            try:
                remaining = self._cancellation.remaining()
                if remaining is not None:
                    timeout = remaining if timeout is None else min(timeout, remaining)
                return self.future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                if cancel_on_timeout:
                    self.cancel()
                raise

        def cancel(self) -> None:
            """
            Cancels the task. If it has not yet started, it will not be executed.
            If it has already started, its future will be marked as cancelled and will raise a CancelledError
            when its result is requested.
            """
            self.future.cancel()

        def wait_until_done(self) -> None:
            """
            Wait for the underlying execution to exit, including after cancellation or timeout.
            A timeout completes the result with an error and requests cooperative cancellation;
            it does not release the executor's ownership of the operation.
            """
            if not self._execution_finished.wait(self._cancellation.remaining()):
                self._set_exception(TimeoutError(f"Task {self.name} exceeded its deadline"))
                self._cancellation.cancel()
                log.warning("Task %s exceeded its deadline; waiting for execution to stop before starting more work", self.name)
                self._execution_finished.wait()

    def _process_task_queue(self) -> None:
        while True:
            # obtain task from the queue
            with self._task_executor_lock:
                self._task_executor_lock.wait_for(lambda: bool(self._task_executor_queue) or self._closed)
                if not self._task_executor_queue:
                    return
                task = self._task_executor_queue.popleft()
                self._task_executor_current_task = task

            # start task execution asynchronously
            if task.logged:
                log.info("Starting execution of %s", task.name)
            task.start()

            # wait for task completion
            task.wait_until_done()
            with self._task_executor_lock:
                self._task_executor_current_task = None
                if task.logged:
                    self._task_executor_last_executed_task_info = self.TaskInfo.from_task(task, is_running=False)

            # call the task completion callback if provided
            if self._task_completion_callback is not None:
                try:
                    self._task_completion_callback()
                except Exception as e:
                    log.error(f"Error in task completion callback after executing {task.name}: {e}", exc_info=e)

    @dataclass
    class TaskInfo:
        name: str
        is_running: bool
        future: Future
        """
        future for accessing the task's result
        """
        task_id: int
        """
        unique identifier of the task
        """
        logged: bool

        def finished_successfully(self) -> bool:
            return self.future.done() and not self.future.cancelled() and self.future.exception() is None

        @staticmethod
        def from_task(task: "TaskExecutor.Task", is_running: bool) -> "TaskExecutor.TaskInfo":
            return TaskExecutor.TaskInfo(name=task.name, is_running=is_running, future=task.future, task_id=id(task), logged=task.logged)

        def cancel(self) -> None:
            self.future.cancel()

    def get_current_tasks(self) -> list[TaskInfo]:
        """
        Gets the list of tasks currently running or queued for execution.
        The function returns a list of thread-safe TaskInfo objects (specifically created for the caller).

        :return: the list of tasks in the execution order (running task first)
        """
        tasks = []
        with self._task_executor_lock:
            if self._task_executor_current_task is not None:
                tasks.append(self.TaskInfo.from_task(self._task_executor_current_task, True))
            for task in self._task_executor_queue:
                if not task.is_done():
                    tasks.append(self.TaskInfo.from_task(task, False))
        return tasks

    def issue_task(self, task: Callable[[], T], name: str | None = None, logged: bool = True, timeout: float | None = None) -> Task[T]:
        """
        Issue a task to the executor for asynchronous execution.
        It is ensured that tasks are executed in the order they are issued, one after another.

        :param task: the task to execute
        :param name: the name of the task for logging purposes; if None, use the task function's name
        :param logged: whether to log management of the task; if False, only errors will be logged
        :param timeout: the maximum time to wait for task completion in seconds, or None to wait indefinitely
        :return: the task object, through which the task's future result can be accessed
        """
        with self._task_executor_lock:
            if self._closed:
                raise RuntimeError("Task executor has been shut down")
            if logged:
                task_prefix_name = f"Task-{self._task_executor_task_index}"
                self._task_executor_task_index += 1
            else:
                task_prefix_name = "BackgroundTask"
            task_name = f"{task_prefix_name}:{name or getattr(task, '__name__', 'task')}"
            if logged:
                log.info(f"Scheduling {task_name}")
            task_obj = self.Task(function=task, name=task_name, logged=logged, timeout=timeout)
            self._task_executor_queue.append(task_obj)
            self._task_executor_lock.notify()
            return task_obj

    def execute_task(self, task: Callable[[], T], name: str | None = None, logged: bool = True, timeout: float | None = None) -> T:
        """
        Executes the given task synchronously via the agent's task executor.
        This is useful for tasks that need to be executed immediately and whose results are needed right away.

        :param task: the task to execute
        :param name: the name of the task for logging purposes; if None, use the task function's name
        :param logged: whether to log management of the task; if False, only errors will be logged
        :param timeout: the maximum time to wait for task completion in seconds, or None to wait indefinitely
        :return: the result of the task execution
        """
        task_obj = self.issue_task(task, name=name, logged=logged, timeout=timeout)
        return task_obj.result(timeout=timeout)

    def get_last_executed_task(self) -> TaskInfo | None:
        """
        Gets information about the last executed task.

        :return: TaskInfo of the last executed task, or None if no task has been executed yet.
        """
        with self._task_executor_lock:
            return self._task_executor_last_executed_task_info

    def shutdown(self, timeout: float = 2.0) -> bool:
        """Reject new work, cancel pending work, and wait for execution to stop.

        :param timeout: the maximum time to wait for execution and callbacks to exit
        :return: whether shutdown has completed; False leaves the executor closed and can be retried.
            A task cannot wait for its own exit, so a call from that task returns False immediately.
        """
        with self._task_executor_lock:
            self._closed = True
            current = self._task_executor_current_task
            for task in self._task_executor_queue:
                task.cancel()
            if current is not None:
                current.cancel()
            self._task_executor_lock.notify_all()
        if self._task_executor_thread is threading.current_thread() or (current is not None and current.is_current_thread()):
            return False
        self._task_executor_thread.join(timeout=timeout)
        return not self._task_executor_thread.is_alive()
