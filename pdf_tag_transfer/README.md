# PDF Tag Transfer 0.2.0

A local desktop app for recovering partial tagging work onto an original PDF.
Keep this folder and `../pdf_tag_inspector` together when using the repository.
The downloadable ZIP bundles the required inspector engine in the app folder.

## Launch

Install Python 3.11+ with Tk (3.12 recommended). On Windows run
`Start_Windows.bat`; on macOS/Linux run `sh start.sh`. First launch installs
`requirements.txt` into `.venv`. Processing stays local. Ubuntu typically needs
`python3-tk` and `python3-venv`. Manual launch: `python pdf_tag_transfer.py`.

## Check content, not just the tree

1. Choose the original untagged PDF and partially tagged reference, then Open /
   Analyze. The source structure is visible immediately. **This does not mean its
   contents have transferred.**
2. Start / Resume or Step page links original text, images and vectors to new tag
   objects. Pause stops after the current operation. Undo page replays earlier
   successful page batches.
3. Watch the **CONTENT: linked/expected regions** and **populated tags** counts.
   Select a tag: the details panel shows **REFERENCE CONTENT** and **OUTPUT LINKED
   CONTENT**, while the previews show bounding boxes. Green output outlines show
   linked content; blue outlines show the selected tag and descendants.
4. Use **Show issues** to see page outcomes, reasons for failures, unresolved
   content and broken tag cross-references. Copy issue details is available there.
   Export report saves these outcomes and content counts as JSON.
5. Save copy writes a separate PDF and reopens it to verify actual content
   references, tag text, glyph/image/vector geometry and ParentTree ownership, as
   well as every page's appearance and extracted text. A tree-only result is
   blocked. Incomplete content requires explicit partial-save confirmation.
6. Open the output in Acrobat Pro (or your tagging editor). Verify a populated
   paragraph, table cell and figure where applicable; create a new tag on a
   previously failing page; save/reopen and confirm it still works.

Navigation and zoom apply to all three previews. Scrolling is independent.
Physical page numbers start at 1. Filters include type, metadata/path, current
page, missing figure alt text and transfer status. Gray ancestors remain for
context. The tree represents the source hierarchy with output-content status.

## How content is recovered

The original page artwork remains the base. The app first compares drawing
instructions with source marking wrappers removed. If instructions match, exact
source boundaries can be applied to original drawing operations.

When PDF editing has regrouped operators or changed resource names, a second path
matches individual glyphs, images and vector primitives by content and position.
It splits text-showing operations at encoded character boundaries, retaining
spacing adjustments and graphics state. Source and original coordinate systems,
page rendering and extracted text must agree. Candidate matches must be unique.
One original text run can therefore populate several distinct source tags.

Fresh page MCIDs, StructParents, structure /K references and ParentTree entries are
created. Structure order and supported metadata are retained. Namespace maps and
valid tag /Ref arrays reconnect to the new objects. Unreachable /Ref targets are
reported, omitted from output, and require partial-save confirmation. They are not
repaired by guessing or importing detached source tag graphs.

Each successful page is serialized, independently reopened and checked before its
status becomes Transferred. Failed page changes are rolled back. Final save
repeats the content checks. A page with no source references is labeled **No source
content**, not Transferred. Untagged continuation pages retain the original artwork.

## Limits

- This cannot infer content for source tags that have no recoverable content
  reference or location. Show issues counts empty source leaves separately.
- Both files need the same page count, coordinate systems, page appearance and
  extracted text. There is no OCR or changed-layout/page-remapping mode.
- A source Form reference can match a complete original Form placement. Forms
  containing several separately tagged regions or mixed tagged/untagged artwork
  cannot yet be split; these remain unresolved. Annotation OBJR references and
  ambiguous/overlapping matches remain unresolved as well.
- The page is the transaction unit: one unresolved region can leave the whole page
  for review. The app does not silently guess missing associations.
- Nested MCIDs, tagged artifacts, unsupported non-MCID marked content, cyclic/shared
  hierarchy, duplicate IDs and direct structure elements need review or normalization.
- The base must have no structure tree or page StructParents. Metadata that points
  back to source page/structure objects is rejected with a field path. Compressed
  metadata streams are supported. Password inputs are not supported by this GUI.
- Properties are read-only. There is no manual content reassignment, session
  persistence or complete PDF/UA validation. Modified digital signatures are not
  retained as valid. Pixel checks use PyMuPDF's default resolution; they do not
  establish identical behavior in every PDF viewer.
- Native Windows GUI use, continued Acrobat tagging and the reported user PDF pair
  have not been validated here. Test your output before using it for remediation.

## Validation

Run `python -m pytest pdf_tag_transfer/tests pdf_tag_inspector/tests -q` from the
repository root with pytest installed, or `python -m pytest tests -q` in an extracted
download. Tests include resegmented text operators, splitting one original text run
between source tags, resource renaming, image/vector links, Form links with/without
explicit page references, multibyte fonts, corrupted /K or ParentTree detection,
empty-output blocking, partial-save confirmation, rollback/undo, metadata, namespace
and tag-reference handling, and input protection.

The GUI needs an interactive display. Callback logic has headless tests; interactive
Windows validation remains outstanding. PyMuPDF is AGPL/commercial software; review
dependency terms before redistribution.
