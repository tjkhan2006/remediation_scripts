# Text Position Fix

A local Python desktop tool that brings existing PDF page text in front of images
and vector artwork, without changing its X/Y placement. It lives inside PDF Repair
Toolbox and follows PDF Tag Inspector's light, three-pane Tkinter interface.

## Start

Requires Python 3.11+ with Tkinter, pip, and venv (Python 3.12 recommended).

- **Windows:** double-click `Start_Windows.bat`. Install Python with Tcl/Tk and
  the Python launcher enabled first.
- **macOS/Linux:** run `sh start.sh`. On Debian/Ubuntu install `python3-tk` and
  `python3-venv` if needed. A desktop display is required.

The launchers create a local `.venv` and check/install pinned dependencies on each
launch; dependency setup needs internet. PDF processing itself stays local.
Optional filename arguments are supported by both launchers.

Manual launch:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
. .venv/bin/activate
python -m pip install -r requirements.txt
python text_pos_fix.py
```

## Workflow

1. Browse for a PDF or enter its path and click **Open PDF**. Supply a password
   if requested. Analysis runs in the background.
2. Select a page on the left. Search its existing text and select a span to see
   read-only properties and a red preview outline.
3. Choose **All pages**, **Current page**, or **Page range** (such as `1-3, 5`).
4. Click **Bring text to front**. The result dialog identifies skipped pages.
5. Switch between **Original** and **Repaired** using the same navigation and
   zoom controls. Original always means the file opened at the start.
6. Use **Undo last repair**, or **Save repaired copy...** to write a new PDF.

Page numbers are physical PDF positions starting at 1. Ctrl/Command+O opens;
Ctrl/Command+S saves. Coordinates in the properties panel are PDF renderer points;
preview outlines account for page rotation.

## Repair behavior

PDF drawing order is changed by partitioning original drawing instructions into
background artwork and foreground text passes. Both retain the original graphics
and text-state instructions, transformations, clipping paths and resource references.
Text is neither extracted and retyped nor painted twice. Text-only Form XObject
invocations can be moved intact, including nested text-only forms. The relative
order within text and within background artwork is retained.

Text remains in its original position, font, size, color, spacing, rotation and
visibility mode. Invisible OCR text remains invisible. This program does not add
OCR or recover text stored only as image pixels or vector outlines. Annotations
and interactive form fields are separate from page content and are not reordered;
they may still appear above page text in a PDF viewer.

Existing structure-tree links, scoped MCIDs, bookmarks, annotations, and other PDF
objects are retained. Text-only MCID wrappers move with text rather than being
duplicated. Logical accessibility reading order is not edited. This is not a
PDF/UA or accessibility compliance validator.

## Conservative skips and verification

An unsupported page is left unchanged and gets a reason in the page preview and
repair result dialog. Other supported pages can still be repaired. Current skips:

- Mixed text/artwork Form XObjects, transparency groups, soft masks, nonstandard
  blending, nonopaque graphics states, and transfer functions.
- Type 3 fonts, text clipping modes, nested MCID scopes, or an MCID spanning both
  text and artwork.
- Malformed/unbalanced content, unknown operators, unresolved resources, and
  marked-content point properties. Extended graphics state inside Forms is
  conservatively skipped.

A repair verifies text trace content, font names, sizes and bounding boxes (to
0.0001 points), and page dimensions. A failed check rolls back the entire selected
repair transaction. Matching bounds are a useful regression check, not a proof of
identical glyph appearance in every viewer; review the preview. Original instructions
and state are retained to preserve the other text properties.

Saving rejects the source path and its filesystem aliases, retains encryption,
checks syntax and page count, verifies text geometry, and uses a temporary file
followed by atomic replacement. Changes can invalidate digital signatures. Review
signed documents before using a modified copy.

Repaired pages carry a content digest so repeat repairs are no-ops while the
content remains unchanged. Undo restores the prior PDF snapshot. Large documents
can require substantial memory for preview and undo snapshots.

## Tests

```sh
python -m pip install pytest
python -m pytest -q tests
```

Tests generate temporary PDFs; `tests/fixtures/README.md` describes the fixture
policy. Coverage includes occluding shapes and images, rotations, clipping,
multiple streams, invisible text, nested forms, tagged content, encryption,
transaction rollback, save, undo, and repeat repairs.

Validated on Linux/Python 3.12 with 14 automated cases and a virtual-display GUI
smoke test covering open, selection/outlines, repair, original/repaired previews,
zoom, save, undo and close. Native Windows/macOS execution has not been tested.

## Files and dependencies

- `text_pos_fix.py`: Tkinter interface and background task handling.
- `repair_core.py`: analysis, repair transactions, preview, undo, verified saving.
- `content_order.py`: drawing-order partitioning and supported-content checks.
- `requirements.txt`: pinned pikepdf, PyMuPDF and Pillow dependencies.
- `Start_Windows.bat` / `start.sh`: setup and launch.

PyMuPDF is available under AGPL/commercial licensing; consult dependency licenses
when redistributing. This version uses the repository as reference. The supplied
Google Drive folder was not accessible through a connected Drive integration.
