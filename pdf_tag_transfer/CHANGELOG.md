# 0.1.2

Support PDF 2.0 namespace dictionaries, root Namespaces lists, tag NS links,
and RoleMapNS mappings, including shared and mutually referenced namespaces.
Rebuild tag Ref arrays against the new tag objects after allocating the tree,
including forward and cyclic cross-references. Diagnose unreachable Ref targets
with the source tag path. Preserve the necessary PDF version when saving/previews.

Regression tests cover namespace identity, cross-namespace maps, schema streams,
unlisted namespaces, Ref targets, PDF versions, save/reopen and undo/replay.
This update has not been tested with the user PDF or interactively on Windows.

# 0.1.1

Fix Open / Analyze rejecting stream-valued tag attributes and ClassMap entries.
Rebuild streams using their encoded bytes and recursively copied metadata; retain
compression filters and parameters. Reject page/structure links with a field path.
Regression tests cover compressed streams, save/reopen, undo, source preservation,
and refusal to import source document structure.

27 transfer and inspector tests pass. This update has not been tested with the
user PDF or interactively on Windows. Existing transfer limitations still apply.
