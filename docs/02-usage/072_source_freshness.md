# Source freshness

Before semantic queries that synchronize the workspace, Selene discovers source files and compares their content fingerprints with its previous observation. Edits remain visible when an editor preserves or decreases the modification time, including replacements of the same size. File buffers also verify their disk content when synchronizing with the language server; an already-open document therefore receives updated text.

If an external edit conflicts with an unsaved buffer, Selene raises a conflict instead of replacing the draft. The buffer can continue after the disk conflict is resolved. This protects the observed buffer state; it does not make subsequent writes atomic or automatically merge edits.

Workspace observations and notification delivery are serialized. Each language server retains its own delivery state. A failed or ambiguous notification is retried, even if the file subsequently returns to its earlier contents. An unreadable or unstable file raises an error instead of being reported as deleted. Notification acceptance means the local transport accepted the message; indexing completion remains dependent on the backend.

Content verification currently reads every discovered source file during synchronization. Large repositories may take longer than with the former timestamp check. Incremental indexing is separate work. Metadata checks surround each file read, with bounded retries when it changes during capture; neither these checks nor the filesystem scan provide a single atomic snapshot of the entire project. Changes after observation may require another synchronization.

These checks use the project's existing file-discovery rules. They do not add filesystem confinement, block child-process networking, or prove freshness for every backend. Source scope, transport security and OS-level privacy controls remain separate requirements. The observations keep fingerprints in memory and do not introduce a remote service or persist an additional source cache.
