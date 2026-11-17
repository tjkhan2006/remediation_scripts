# PDF Tag Link Diagnostic

Read-only evidence collection for an Adobe Acrobat Pro Fix Reading Order failure. No repair has been demonstrated. The native Windows module is **source only: not compiled against installed SDK headers and not executed in Acrobat**.

## Start on Windows

1. Install Python 3.12+ with the Python launcher and Tcl/Tk support.
2. Open a terminal in this folder and run `py -3 -m pip install -r requirements.txt`.
3. Double-click `Start_Windows.bat`. Choose the PDF and an output folder. Leave “Export full document HTML report” selected to get a readable report containing the complete exported analytics, plus JSON and JSONL for an agent. Object fingerprints support before/after comparisons.

The reports run locally and can include existing document text in tag attributes, identifiers, and dictionaries. They are not uploaded by the tool. The analyzer reads the PDF without saving it and checks its SHA-256 before and after. Historical inputs and generated reports are excluded from Git by default.

## CLI

```powershell
py -3 diagnostic.py audit "working.pdf" --objects --out reports/working.json --html reports/working.html --jsonl logs/working.jsonl
py -3 diagnostic.py audit "after.pdf" --objects --out reports/after.json --html reports/after.html
py -3 diagnostic.py compare reports/working.json reports/after.json --out reports/delta.json --html reports/delta.html
py -3 object_dump.py "after.pdf" 106864:0 --out reports/object.json
```

Use actual object numbers from that specific PDF. `object_dump.py --streams` includes decoded stream bytes as base64. Reports never overwrite the input PDF. Audit mode rejects malformed PDFs that would require parser recovery; inspect a failure explicitly rather than treating recovered structure as authoritative.

`diagnostic.py` inventories all pages, recursively invoked Form XObjects, BMC/BDC/EMC nesting, inline/named MCID properties, page/stream MCID namespaces, forward logical references, reverse ParentTree mappings, reachable tags, direct parent consistency, IDTree aliases, class references, role-map cycles, stream hashes, and optional current-object fingerprints. A reused Form's content is counted once per page/owner; reuse occurrences are recorded separately. Untagged content without MCIDs is not automatically a defect.

The comparison exports changed records and object hashes. Object numbers are local to each file. A rewrite can renumber everything; reference diffs alone cannot establish semantic damage. Decoded stream and operator hashes help distinguish encoding changes from content changes. Operator hashes exclude inline image bytes; decoded stream hashes cover them. This is a current-object comparison, not an incremental revision-history parser. Annotation appearance streams, patterns and Type 3 glyph content are outside the content parser's scope; OBJR references and annotation dictionaries are retained. Number/name-tree validation covers observed leaves/order/duplicates, not every PDF conformance rule. This is not a PDF/UA validator.

## Reproduce the Acrobat operation

Read [the test protocol](docs/ACROBAT_TEST_PROTOCOL.md) before capturing results.

```powershell
py -3 prepare_cases.py --october "october.pdf" --working "working.pdf" --out "captures/run-001"
py -3 make_controls.py --october "october.pdf" --working "working.pdf" --out "probes/run-001"
```

Both commands require a new output directory. The first copies inputs byte for byte and creates an editable `run.json` manifest. The second creates explicitly labeled derivative controls and a hash manifest. None is a repaired master. Only those control derivatives intentionally change PDF representation; the diagnostic tools do not write PDFs.

For candidate regression checks, install optional renderer dependencies and compare all pages:

```powershell
py -3 -m pip install -r requirements-render.txt
py -3 verify_preservation.py "before.pdf" "candidate.pdf" --out reports/preservation.json
```

This compares rendered pixels, extracted text, page geometry, links, and existing tag records at their logical paths. Renumbering/insertion can require manual review. Pixel equality at one DPI is limited evidence; table semantics and accessibility need review. An equal tag count alone never proves preservation.

## Native Acrobat module

See [Windows SDK setup and build](sdk_plugin/README.md). The module is designed to run inside Adobe's official BasicUI x64 sample and inspect live in-memory state before and after each UI operation. It uses documented parent-lookup APIs and exports JSONL. Exact-signature compiler checks and installed-header manifests are supplied, but have **not run in this Linux workspace**. No `.api` binary is shipped.

## Current evidence

See [findings and repair hypothesis](docs/FINDINGS.md) and [Adobe API sources](docs/ADOBE_API_SOURCES.md). All three supplied PDFs have been statically audited. The confirmed working-copy hash is `df9a61a89a1d29e9e57d9f852b43af86cb2ccc83e58c6ee21cafe2afd4f9184d`. Its 8,580 reachable tags remain untouched. Live Acrobat success/failure captures are still needed to identify the first observable divergence.

## Test the implementation

```powershell
py -3 -m unittest discover -s tests -v
```

Tests cover valid and missing links, no-MCID containers, detached tags, named properties, reused Form namespaces, artifact contexts, stale IDs, graph cycles, comparisons, source-overwrite rejection, independent test copies and control generation. The native module and Tk launcher require Windows/desktop testing separately.
