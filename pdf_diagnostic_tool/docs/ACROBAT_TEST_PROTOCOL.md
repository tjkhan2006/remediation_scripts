# Acrobat capture protocol

Status: **all live Acrobat cases below are NOT RUN in this investigation**. Prior user observations are recorded separately. Use Acrobat Pro 2026.002.22031 x64, or record any different build. Record Windows version and whether the old or new UI is active. Complete runs on the same installation before comparing builds.

## 1. Inputs and matching selection

Use `prepare_cases.py` to create separate input copies and `run.json`. Keep supplied originals untouched. Open only one case at a time. Do not reuse the output of one case as another's baseline, except in the explicitly named seed-then-FRO experiment.

Start with **physical PDF page 12**, and record the displayed page label separately. Choose the same small text region in October and working copies, avoiding borders and adjacent columns. Use the text `First-Year Students` near the left side of the page as a proposed reproducible region; confirm it matches the known failure before using it for all cases.

Static text geometry in the working copy suggests an initial rectangle approximately `(30, 98, 144, 118)` points in a **top-left origin, y-down** coordinate system. On the 792×612 page this is approximately `(30, 494, 144, 514)` in a bottom-left origin, y-up system. These are selection guidance, not proof of what Acrobat selects. Save a screenshot of the actual rectangle and record actual text/coordinates in `run.json`. If this region does not reproduce, use the user's known failing region consistently and record it.

For successful selection-tagging, highlight that same text and invoke **Create Tag from Selection**, using a paragraph tag when available. The selection mechanisms differ; record actual content captured rather than assuming rectangle/text highlight equivalence.

## 2. Capture cases

| Case | Input | Action | Required observations |
|---|---|---|---|
| `oct_fro` | Untouched October copy | Fix Reading Order → Text/Paragraph | Positive control: logical tag appears and persists |
| `working_save_only` | Untouched working copy | Save As, no tagging | Serializer/UI-save baseline |
| `working_fro` | Independent working copy | Same FRO action and region | Content container, logical tag, exact error, persistence |
| `working_selection` | Independent working copy | Create Tag from Selection | Successful-path logical association |
| `working_seed_then_fro` | Independent working copy | Create Tag from Selection; save/reopen; FRO on adjacent untagged text | Whether initializing page-level structure changes FRO behavior |

For each case:

1. Verify the `before.pdf` SHA-256 against `run.json`; record application/build details and UTC time.
2. If the native module is compiled and loaded, run a live audit and save a unique `live-before.jsonl`.
3. Perform exactly one prescribed action. Record the selected classification, tag created (or absent), Content panel entry and exact **Show In Tags Panel** response. Take screenshots of both panels. Do not assume the UI's word “ID” refers to `/IDTree` or MCID.
4. Run `live-after-unsaved.jsonl`, if available. It captures state before saving.
5. Save As a new `after.pdf` in that case's directory. Close and reopen **that saved file**. Repeat panel checks and optionally run `live-reopened.jsonl`.
6. Fill in `run.json`, including failed/no-op outcomes. Keep `before.pdf` unchanged. Audit before and after with `--objects`, then compare their JSON inventories. Use `object_dump.py` for actual dictionary/stream bytes at changed object numbers.

Example:

```powershell
py -3 diagnostic.py audit captures/run-001/working_fro/before.pdf --objects --out reports/fro-before.json --html reports/fro-before.html --jsonl logs/fro-before.jsonl
py -3 diagnostic.py audit captures/run-001/working_fro/after.pdf --objects --out reports/fro-after.json --html reports/fro-after.html --jsonl logs/fro-after.jsonl
py -3 diagnostic.py compare reports/fro-before.json reports/fro-after.json --out reports/fro-delta.json --html reports/fro-delta.html
```

Repeat for the successful selection path and save-only path. Compare both action deltas with the save-only delta. Inspect the full page/stream MCID namespace, not just a global count. If an operation changes stream/object numbering, correlate by page, actual text, normalized operator hashes, logical paths and structure IDs.

## 3. October-based controls

After confirming untouched October success, test generated controls in this order:

1. `october_resaved.pdf`, physical page 12.
2. `october_base_working_page12.pdf`, physical page 12.
3. `single_october12.pdf`, physical page 1.
4. `single_working12.pdf`, physical page 1.

Always save an independent post-operation output and reopen it. Generated files have **NOT RUN** status. The inverse control deliberately removes the donor page's stale `/StructParents`, while retaining October's tag tree and other pages. Single-page controls deliberately have no logical tag tree. No repaired master is produced.

If untouched October works but resaved October fails, the serializer is a confound: stop interpreting the inverse result as evidence against the original November structure. If resaved October works and the inverse succeeds, the working page can be tagged in October document context. If the inverse fails, page representation/resources or their interaction with that context is implicated. Standalone results provide supporting evidence and can themselves introduce cloning/untagged-document confounds.

## 4. Interpret first observable divergence

| Saved/live evidence | Supported conclusion |
|---|---|
| New BDC without MCID | Marked content exists without the usual MCID identity; ParentTree-only repair cannot link that new container |
| MCID but no reverse mapping | Missing content-to-tag association |
| Reverse mapping targets root-unreachable tag | Orphaned logical association |
| Reachable mapping but no matching forward `/K` reference | Inconsistent bidirectional relationship |
| Complete matching association but UI cannot navigate | Investigate saved/reopened UI/native lookup behavior |
| Live association exists but disappears after save | Persistence/serialization stage implicated |
| No saved change | Verify save/action completion before inferring structure failure |

Do not infer an internal SDK call sequence from output bytes. Public APIs may establish only the first observable broken invariant. Keep expected untagged content distinct from invalid tagging attempted by the operation.

## 5. Any later repair candidate

No repair is authorized by a diagnostic control's success alone. Isolate a minimal hypothesis and propose it with supporting object evidence before a separate repair implementation. Preserve existing November reachable tags/relationships, both annotations, all 50 pages, text, table semantics and reading order. Run all-page preservation checks and manual table review. A valid success requires FRO to create a reachable tag on page 12, Show In Tags Panel to select it, and the tag to survive save/reopen. Test continuation pages such as 13 and 50 and confirm Create Tag from Selection still works. A static parse or equal count is insufficient.
