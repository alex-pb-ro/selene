# Cancellation and timeouts

Selene executes operations in order. A timeout or cancellation can return an error to the client before the underlying operation has stopped. Selene keeps that operation's place in the executor until it exits, then starts the next queued operation. The dashboard continues to show an exiting operation as running even when its result has been cancelled.

The configured `tool_timeout` includes time spent in Selene's task queue. Cancelling a queued operation prevents its execution. Cancellation also propagates from an MCP `notifications/cancelled` message to the associated operation. A slow tool runs outside the MCP event loop, so protocol messages such as ping and cancellation remain responsive.

Cancellation is cooperative. File and memory writes check for cancellation before committing changes; managed shell commands stop their process tree and drain output before yielding their place in the executor. On POSIX, shell commands run in a separate process group so cleanup can stop descendants even if the shell exits first. Server shutdown rejects new tasks, requests cancellation, and waits for cleanup before releasing project services; stopping those services can help interrupt a blocked operation, after which shutdown waits again.

An operation that ignores cancellation can hold the queue until it returns. A write that already started may finish, and earlier writes in a multi-file operation can remain. Cancellation does not roll back changes. Inspect affected files after a failed mutation before deciding whether to retry. Selene automatically retries only explicitly read-only symbolic tools after a language-server failure; other tools report an uncertain outcome instead of repeating the operation.

These guarantees cover Selene's execution and its managed local shell process group. They do not prove that a separately running IDE has cancelled work already accepted over HTTP, or that a program deliberately detached from its process group has stopped. Windows uses the existing process-tree cleanup and needs platform-specific validation. Uncooperative code can also outlast the bounded shutdown wait. OS isolation remains necessary for the strict data boundary described in the security audit.

## Verification

The executor tests cover FIFO ordering, queued cancellation, deadlines, cancellation while a function remains active, callback ordering, preservation of file contents, parent-request cancellation, shutdown and exceptions. Shell tests include a descendant that ignores `SIGTERM`. Tool tests distinguish recovery of a symbolic read from a mutation whose first attempt already changed a file.

`research/probes/cancellation.py` runs a real stdio MCP server against a synthetic project. It verifies ping while a shell command is running, sends an explicit cancellation notification, exercises the configured timeout, checks that a later tool succeeds after the child stops, and checks process cleanup on disconnect. It makes no model calls. Results are recorded separately from the historical optimization baseline.
