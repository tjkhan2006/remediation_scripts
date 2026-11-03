PDF TAG INSPECTOR
Python desktop app for exploring and editing PDF accessibility tags.

START ON WINDOWS
1. Install Python 3.11 or newer (Python 3.12 recommended) from python.org.
   Include Tcl/Tk, pip, and the Python launcher during installation.
2. Extract the entire ZIP to a writable folder. Do not run inside the ZIP.
3. Double-click Start_Windows.bat.
   The first launch creates a local .venv and downloads the listed dependencies.
   Subsequent launches use that environment without downloading dependencies.
4. Click Browse... and choose a PDF, or open the included demo_tagged.pdf.

START ON MACOS OR LINUX
Install Python 3.11+ with Tk, then run: sh start.sh
On Ubuntu/Debian, Tk and venv are usually supplied by python3-tk and python3-venv.
This app requires a desktop display. It is not a web application.

MANUAL START
    python -m venv .venv
    .venv\Scripts\activate              (Windows)
    source .venv/bin/activate            (macOS/Linux)
    python -m pip install -r requirements.txt
    python pdf_tag_inspector.py
Optional: python pdf_tag_inspector.py "C:\path\document.pdf"

WORKFLOW
- Browse/Open PDF loads the actual structure tree and renders PDF pages.
- Filter by original or mapped tag type, PDF page number, and tag metadata.
  The search includes title, alternate/actual/expansion text, ID, language,
  dictionary attributes, and structure path. It is NOT a full-page text search.
- Figures without alt text filters Figure roles without a nonempty /Alt value.
  This is a convenience filter, not a complete accessibility error diagnosis.
- Use Filtered list or Tag tree. Gray tree rows are ancestors retained for context.
- Select a tag to jump to its page. Container tags include descendant content.
- For tags spanning pages, use Selected tag pages. The other page controls browse
  every PDF page. Page numbers are physical PDF positions starting at 1, and may
  differ from printed numbers or custom page labels.
- Preview supports fit page, fit width, zoom, scrolling, and red content outlines.
- Tag structure & text shows references, children, attributes, and extracted text.
  Text is grouped by content reference, not a screen-reader reading-order simulation.
- Export results saves the filtered tag metadata to CSV or JSON.

OBJECT PROPERTIES PANEL
Content tab:
  Container type, container tag, mapped structure role, effective inherited
  language, full structure path, editable expansion text (/E), tag dictionary.
Tag tab:
  Editable tag type (/S), title (/T), actual text (/ActualText), alternate text
  (/Alt, also used for link descriptions), and language (/Lang).
  The tag ID (/ID), attribute objects (/A), and attribute classes (/C plus
  /ClassMap definitions) are available for inspection. They are read-only.
Color tab:
  Available fill/stroke color spaces and values, image color-space descriptions,
  and rendering intents from the selected page's marked content. A container
  may contain multiple color spaces. This panel is read-only; it does not convert
  colors, embed ICC profiles, or emulate Acrobat's color management interface.
  Some extended graphics state and complex image color information may not be
  resolved by the underlying parser; absence of information is not a default
  color-space assertion.

EDIT AND SAVE
1. Select a tag and edit fields in the properties panel.
2. Click Apply changes to tag. Blank fields remove the corresponding property.
3. Undo last applied edit reverses the last session edit, including across tags.
4. Save edited copy... writes and verifies a new PDF. The original path and
   aliases of that file cannot be overwritten. Existing copies use the standard
   save-dialog overwrite prompt. Saving is performed via an atomic replacement.
Unapplied field changes must be applied before saving. The application prompts
before discarding unapplied fields or unsaved applied edits.

SCOPE AND LIMITS
- This version edits tag types and metadata; it does not add/delete/move tags,
  repair tables, edit attribute dictionaries, or change page artwork.
- Structure traversal includes custom RoleMap roles, nested children, inherited
  page references, ParentTree page fallbacks, MCR/OBJR references, and Form XObjects.
- Outlines use MCID-linked text/image/vector bounding boxes or annotation Rects.
  MCID numbers are scoped to their page or Form stream. Rotations, crops, and
  page scaling are accounted for. Bounds are not exact painted shapes: clipping,
  font metrics, transparency, and damaged content streams can affect precision.
- Tags lacking usable page/content references are shown with unknown locations
  or unavailable outlines. Untagged PDFs still render but have no structure tags
  to inspect. The app does not infer missing tags or perform OCR.
- Password-protected PDFs prompt for a password. Encryption is retained on save.
  Changes to a digitally signed PDF may invalidate its signatures.
- This is an inspector/editor, not a PDF/UA or WCAG compliance validator.
- PDF processing stays local. The launcher's first dependency installation needs
  internet access; the application itself does not upload or send PDF content.
- Tested here on Linux with Python 3.12: 16 automated engine cases and a GUI smoke
  test covering open/filter/select/properties/edit/save/navigation/close. Windows
  launch instructions are included; native Windows execution was not available.
- The supplied Drive references were not accessible during development. The GUI
  was based on the screenshots, without incorporating those reference scripts.

KEYBOARD
Ctrl+O: Open PDF. Ctrl+F: Focus search. Ctrl+S: Save edited copy.
macOS also supports Command+O and Command+S.
Enter in the page-number field goes to that page. Arrow keys move through tags.
Tab moves among controls. Multiline property fields use Tab to advance focus.

FILES
pdf_tag_inspector.py   Tkinter GUI
engine.py              Structure parsing, geometry, properties, edits, exports
requirements.txt       Versions used in validation
Start_Windows.bat      Windows setup and launcher
start.sh              macOS/Linux setup and launcher
make_demo.py           Generates the included tagged demo PDF
demo_tagged.pdf        Two-page example with figures, paragraphs, table and link
tests/test_engine.py   Automated regression tests

TESTS
Install pytest in your environment and run: python -m pytest -q

DEPENDENCIES
This distribution contains original application source; dependencies are installed
separately. PyMuPDF is distributed under AGPL/commercial licensing. Review its
licensing if you redistribute or integrate this app into a proprietary product.
See each dependency's distribution for its own license.
