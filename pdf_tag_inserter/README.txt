PDF TAG INSERTER
Insert consecutive empty or populated tags anywhere in a PDF structure tree.

WINDOWS QUICK START
1. Install Python 3.11 or newer with Tcl/Tk and pip (Python 3.12 recommended).
2. Extract this ZIP into a writable folder.
3. Double-click Start_Windows.bat. The first run installs dependencies into .venv.
4. Browse/Open a PDF. The included demo_tagged.pdf is a useful starting point.

macOS / LINUX
Install Python 3.11+ with Tk and venv, then run: sh start.sh
Manual launch: python -m pip install -r requirements.txt
               python pdf_tag_inserter.py
A desktop display is required. Processing stays on your computer.

THE FULL TAG TREE PANEL
The entire structure hierarchy is on the left, including content references.
Use Expand all and Collapse all, and scroll horizontally or vertically as needed.
The tag-type dropdown lists only types present in the open PDF, plus All tags.
Choose a type to show matching tags, their contents, and their ancestors.
Optional search matches labels and text properties; gray rows provide context.
Clear filters restores the full tree. Click a visible item to choose the anchor.
Insertion clears the filters so the newly inserted tags are visible.
New tags appear in green after insertion. Existing tags stay in their original
relative order, except for content references you explicitly move to new tags.

CONSECUTIVE INSERTION
Pick a tag type such as P, TD, TH, Span, Figure, or a custom role name.
Choose one of these placements:
- Before selected: insert the batch immediately before the selected tree item.
- After selected: insert the batch immediately after the selected tree item.
- First children: insert the batch at the beginning of the selected container.
- Last children: append the batch inside the selected container.
- At child position: insert at a specific 1-based position among direct children.
  Content-reference items count as children. A position of child count + 1 appends.
The entire batch is consecutive, in its specified order. Every inserted tag has
its own structure object and a correct parent link. The tree refreshes immediately.
You can repeat batches with different types to build the hierarchy you need.

THREE POPULATION MODES
1. Empty tags
   Enter any positive whole-number count. Creates containers without content or
   text properties. There is no application-level count cap; available memory
   and PDF size determine practical limits. A 1,001-tag batch was tested.

2. Text properties
   Creates the requested number of tags with title, alternate text, actual text,
   language, and/or expansion text. Properties repeat on each tag. Use {n} in a
   property to insert the sequence number, starting at 1 for that batch.
   Example: title "Cell {n}" produces Cell 1, Cell 2, Cell 3.
   These properties do not add visible text or artwork to the PDF page.

3. Existing page content
   Select a PDF page and click Scan / show page. The list includes:
   - Existing marked content with a resolvable structure reference.
   - Unassigned page-level marked content.
   - Untagged text objects, image placements, vector painting operations, and
     reusable Form artwork without internal marked content.
   Ctrl/Shift-click items and inspect their red outlines in the page preview.
   Click Add selected content to batch. You may collect items from several pages.
   Move up/down changes the insertion order. Remove/Clear adjusts the batch.
   One new tag is created for each batch item. The count follows the batch.
   Optional text properties can also be applied to content-linked tags.
   Choose the destination in the full tree, then click Insert batch.

CONTENT OWNERSHIP
For previously untagged objects, the app wraps the chosen drawing/text operation
with marked-content operators, assigns an MCID, and updates the ParentTree.
For already-tagged content, the app moves the reference out of its old tag and
updates its ParentTree owner. The old tag remains in place, possibly empty.
It does not duplicate visible content references between tags.
Original page drawing operations are retained. Render comparisons passed for the
included text/vector test document after content tagging and reassignment.

SAVE AND UNDO
Undo last insertion restores the PDF state before that entire batch, including
content streams and ownership mappings. Undo snapshots are held in memory, so
many batches on very large PDFs can consume substantial RAM.
Save PDF copy... writes a separate PDF and checks it can be reopened. The open
original file cannot be overwritten, including through an alias. Password-protected
PDFs prompt for a password, and encryption is retained in saved copies.
Saving a modified digitally signed PDF may invalidate its signature.

CONTENT PICKER LIMITS
Content selection follows PDF objects/marked-content sequences, not arbitrary
words or dragged rectangular regions. One text object can contain several lines.
Existing nested MCIDs, inconsistent ParentTree ownership, cyclic structure tags,
or direct (non-indirect) destination containers may need repair before editing.
The picker does not convert artifacts, select inline images, or reassign annotation
OBJR references. Existing Form content is selectable when a page-associated MCR
reference identifies it. Mixed marked/untagged content inside a Form is not split.
Content without resolvable page associations may be absent from the picker.
The full structure tree still shows its entries.
Outlines are bounding boxes, not exact painted shapes. Clipping and font metrics
can affect them. The app does not validate semantic tag nesting, reading order,
table rules, PDF/UA, or WCAG compliance; choose appropriate roles and placement.

VALIDATION
16 automated tests passed, covering all five insertion placements, scalar/mixed
children, large batches, text properties, content reassignment, untagged content,
Form references, ownership rollback, undo, encryption, and save-copy behavior.
A Linux GUI smoke test passed for full-tree display, scanning/preview, consecutive
insertion, undo, content batches, and saving. Windows execution was not available.
Run tests after installing pytest: python -m pytest -q

FILES
pdf_tag_inserter.py     GUI
inserter_core.py        Tree insertion, content ownership, undo, saving
content_geometry.py    Scoped content bounds extraction
tree_filter.py         Tree filtering with original insertion anchors
requirements.txt       Dependency versions used for validation
Start_Windows.bat       Windows setup/launcher
start.sh               macOS/Linux setup/launcher
demo_tagged.pdf         Example PDF
tests/test_inserter.py  Regression tests

Dependencies are installed separately. PyMuPDF is available under AGPL/commercial
licensing; review its terms if redistributing or integrating into proprietary
software. Refer to the individual dependency distributions for their licenses.
