# 0.2.0

Recover actual content when source editing regrouped text operators or renamed
resources: match glyphs/images/vectors against original positions and content,
and safely split encoded text runs. Support whole source Form tags mapped to
original Form placements. Retain exact-boundary transfer when operators agree.

Reopen each serialized transferred page and the final output to verify actual
/K content, text/geometry and ParentTree ownership. Roll back failed page changes.
Block tree-only saving; require explicit confirmation for incomplete content.
Display linked-content/populated-tag counts, selected source/output text and a
Show issues window with Copy issue details. Reports include content counts.
Do not call pages without source content references Transferred.

Existing unsupported/ambiguous content remains unresolved, including Forms that
need internal splitting and annotation references. This is not proof of continued
Acrobat tagging success. The user PDFs and interactive Windows use remain untested.

# 0.1.3

Open documents with Ref targets outside the recovered hierarchy. Preserve valid
Ref entries and report unresolved entries by source tag path and object number.
Do not import detached tag graphs or guess replacement targets. Unresolved Ref
entries are omitted from output; their tags and ancestors stay Needs review,
even after content transfer. Show a persistent warning and per-tag details;
include every issue in Export report. Require explicit partial-save confirmation
for omitted cross-references, including when all content transferred successfully.
Undo/replay regenerates issues without duplicates. Inputs remain unchanged.

33 transfer/inspector tests pass; GUI save logic is tested without a display.
Interactive Windows use and the user document remain untested.

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
