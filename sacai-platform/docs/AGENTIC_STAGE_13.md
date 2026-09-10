# Stage 13 design review: future agentic file editing

This capability is deliberately not implemented.

A later service may expose separate read, propose-patch, apply-approved-patch,
and test operations. Every path must be resolved below one configured project
root; symlinks escaping that root are rejected. Read and write capabilities use
different grants. Writes require a displayed diff and explicit human approval,
while deletions use the existing preview-token pattern. No general shell, root
filesystem access, network access, credential reads, or autonomous approval is
allowed. Each request, diff, approver, result, and test output is appended to
the scientific audit store. Run the service in its own unprivileged container
with the project mounted read-only until an approved write operation creates a
short-lived narrowly scoped workspace.

Before implementation, repeat the source/security review against the then-
current OpenWebUI release and threat-model prompt injection, symlinks, git
hooks, build scripts, secrets, concurrent edits, and rollback.

