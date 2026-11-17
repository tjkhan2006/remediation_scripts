# PDF Tag Transfer

First implementation of a local desktop app for recovering partial tagging work
onto the original untagged PDF. Its layout and tag inspection come from
`../pdf_tag_inspector`. Keep both folders together in the repository.

## Launch

Install Python 3.11+ with Tk (3.12 recommended). On Windows double-click
`Start_Windows.bat`; on macOS/Linux run `sh start.sh`. First launch downloads
Python dependencies into a local `.venv`. PDF processing itself stays local.
Ubuntu typically needs `python3-tk` and `python3-venv` installed.

Manual launch: install `requirements.txt`, then run `python pdf_tag_transfer.py`.

## Workflow

1. Choose the **original untagged PDF** and **partially tagged reference**.
2. Open / Analyze loads the source hierarchy and initializes a new structure tree
   on a separate in-memory copy of the original.
3. Start / Resume transfers one page per batch. Pause stops after the current
   operation. Step page processes the next pending page; Undo page reverses the
   most recent successful page batch. It rebuilds earlier successful batches.
4. Select a tree tag to see its content in all three previews. Blue outlines show
   the selection; green output outlines show applied content. Container selection
   includes descendants. Page and zoom controls apply to all three previews;
   scrolling is independent. Page numbers are physical positions, starting at 1.
5. Filter by type, metadata/path search, current page, missing figure alt text,
   and transfer status. Gray ancestors remain for context.
6. Export report writes page outcomes and unresolved source references to JSON.
7. Save copy writes a separate PDF, reopens it, checks syntax and compares every
   page's rendered appearance and extracted text with the original. Partial
   saves require confirmation. Inputs and their filesystem aliases are protected.

The output artwork does not animate or redraw progressively: it is the original
artwork throughout. Actual page tagging is applied in batches; the output tree
status and outlines refresh after completed changes. Empty source containers are
retained. Untagged continuation pages remain available for future tagging.

## Matching and preservation

This version deliberately supports **unchanged page-stream artwork**. It compares
coordinate systems, extracted text, rendered pixels, and parsed drawing
instructions with marked-content wrappers removed. Equivalent page drawing
instructions allow exact source tag boundaries to be applied to original
instructions, including several tags within a single text object. Existing
source object numbers, ParentTree and stale ID indexes are not copied.

Fresh structure elements, MCIDs, page StructParents, ParentTree, parent links and
IDTree are built. Source child/content order, tag roles, title, alt/actual/expansion
text, language, IDs, attribute dictionaries, RoleMap and ClassMap are retained
when representable. Geometry/rendering reuse the inspector engine. Output tag
structure is inspected from a newly serialized preview after each batch.

## Current limits / next work

- Both files must have the same page count. Changed page content, resource-name
  changes, geometry changes and other drawing-instruction differences require
  review. There is no geometric fallback or manual reassignment editor yet.
- Marked Forms, annotation OBJR links, nested MCIDs, tagged artifacts, unsupported
  non-MCID marked content, and ambiguous ownership are not transferred
  automatically. Unresolved references are reported, never guessed.
- Form/annotation-dependent tags can remain empty or partially linked in the
  output. Partial saves are for continued remediation, not completed accessibility.
- The base must have no structure tree or page StructParents. Namespace/Ref
  metadata, direct structure elements, duplicate IDs and cyclic/shared source
  structure require normalization before opening. Metadata streams, including compressed attribute streams, are preserved.
  Metadata that points back to source pages or structure is rejected with a field path. This app does not copy the damaged document's page artwork.
- Properties are displayed for review; tag editing and a separate output-tree
  browser are future work. Current tree shows source hierarchy with output status.
  There is no OCR, page remapping, session persistence or compliance validation.
- Password-protected inputs are not supported by this GUI. Modifying signed
  documents does not preserve signature validity.
- Pixel comparison uses PyMuPDF at its default resolution. This does not prove
  equivalent rendering in every viewer or complete PDF/UA correctness.

**Continued tagging in Acrobat has not been validated.** Test the saved copy in
Acrobat Pro: create a tag with Reading Order on a formerly failing page, use
Show In Tags Panel, save, reopen, and repeat on a continuation page. The related
repository investigation does not establish a proven root cause for the reported
Acrobat failure. Do not treat a successful transfer as proof it fixes that failure.

## Validation

Engine tests cover exact intra-text-object boundaries, metadata and ID indexes,
changed pages, duplicate ownership/IDs, nested MCIDs, marked Forms, undo/replay,
separate saves, and input aliases. Run `python -m pytest tests -q` after installing
pytest. Inspector regression tests can be run from the repository root alongside
these tests. Native Windows and interactive GUI execution have not been validated
in the headless development environment.

PyMuPDF is AGPL/commercial software; check dependency terms before redistribution.
