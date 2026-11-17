# 0.1.1

Fix Open / Analyze rejecting stream-valued tag attributes and ClassMap entries.
Rebuild streams using their encoded bytes and recursively copied metadata; retain
compression filters and parameters. Reject page/structure links with a field path.
Regression tests cover compressed streams, save/reopen, undo, source preservation,
and refusal to import source document structure.

27 transfer and inspector tests pass. This update has not been tested with the
user PDF or interactively on Windows. Existing transfer limitations still apply.
