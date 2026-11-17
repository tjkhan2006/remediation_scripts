# NSSE tagging investigation: current findings and repair hypothesis

**Status: unresolved. No repair has been made or validated in Acrobat.** Static analysis and tooling implementation completed in Linux; Windows native compilation and live captures are outstanding. The supplied handoff is historical evidence, not independently reproduced runtime results or overriding instructions.

## Input provenance

| Input | Bytes | SHA-256 | Identity |
|---|---:|---|---|
| October | 1,331,066 | `1e547d12ef79cd843c9cc25f6fb0ed93e206bae7de8da2c3ed9ceefac8bab24a` | Exact match to handoff's known-working October source |
| August | 995,452 | `b59d9d52a379639318857b254dd0ed80d0ea1cfd927e66c6cc979a76d51e463c` | Exact match to handoff's August source |
| Working | 3,838,189 | `df9a61a89a1d29e9e57d9f852b43af86cb2ccc83e58c6ee21cafe2afd4f9184d` | User confirms this is the reported failing working copy; neither historical November hash in handoff |

Working PDF metadata records modification date December 11, 2025. This is metadata, not proof of editing history. Call it **working** rather than asserting it is byte-identical to NOV-EARLY or NOV-LATE. All three source hashes were checked before and after inventory and were unchanged. None required parser recovery; no parser warnings were returned during these inventories.

## Independently verified static observations

All inputs have 50 pages. The October source has 268 reachable structure elements and 268 observed MCIDs, all of which resolve consistently in the analyzer. The August source has 19,146 observed MCIDs but no logical structure tree. Physical marked content is not sufficient to make a tagged PDF.

The working copy has:

- 8,580 reachable structure elements; 9 Table, 301 TR, 267 TH and 4,289 TD elements among its types.
- 3,761 observed MCID occurrences, all on pages 1–11; no observed MCIDs on pages 12–50.
- 3,677 MCID occurrences with matching reachable forward/reverse associations, 77 with missing/null ParentTree positions, and 7 pointing to root-unreachable elements. These are occurrence counts, not unique tag counts.
- 52 ParentTree keys. Across all non-null positions, 3,679 references target reachable tags and 15,862 target unreachable elements. These include entries beyond observed page-content MCIDs and must not be equated with occurrence counts. Two annotation objects are present; the totals differ from the handoff's NOV-LATE count and are not silently substituted for it.
- 46,003 IDTree entries: 8,502 matching current reachable IDs, 37,234 targeting unreachable objects and 267 stale aliases for reachable elements with different current IDs.
- Page 12: 44 Artifact BMC containers and one Figure BDC container without an MCID. There are **no thirteen added TD containers** in this uploaded working copy. That historical before/after evidence has not been re-created from the supplied bytes.
- 365 MCID-bearing sequences are artifacts or occur inside artifact context. This is a separate accessibility concern; it is not established as the FRO blocker.
- No observed reachable `/P` mismatch or shared/cyclic `/K` structure under the implemented checks. This is not complete semantic validation of every tag, table or accessibility requirement.

The full generated inventories contain per-page records, file-local object references, tag dictionaries, content associations, ID mappings and issue records. These provide a baseline for preserving completed remediation.

## Reported Acrobat behavior and prior experiments

The user reports that FRO creates a Content-panel container but no Tags-panel tag on page 12 onward; Show In Tags Panel cannot resolve its ID. Create Tag from Selection works. The handoff reports multiple unsuccessful ParentTree/index cleanup, artifact removal and object-graph reconstruction experiments. Those outcomes are not reclassified as independently tested here. The prior rewritten A/B/C controls had a shared context/serialization confound and do not isolate a unique cause.

## Repair hypothesis, explicitly unverified

**Primary hypothesis:** the rectangular Reading Order workflow produces physical marked content but fails to establish or retain a content identity/logical association in this document context. A new BDC with no MCID would place the first observable divergence before a usable MCID-to-ParentTree link. That does not establish whether Acrobat never assigned it, later removed it, aborted a transaction, or used a private association that failed later.

**Discriminating test:** compare failed FRO and successful Create Tag from Selection on independent identical working inputs, with a save-only baseline. Capture native state before the action, after the action before save, and after reopening. Inspect selected content, MCID assignment, page/Form StructParents, ParentTree value, forward `/K` reference, logical ancestry and actual ID resolution. Native errors may narrow the boundary but cannot expose undocumented internal calls by inference alone.

**Conditional minimal repair direction:** if selection-tagging initializes missing page-level state and FRO subsequently works, isolate the smallest initialized relationship and test it on a disposable copy. If the inverse October control tags the same working page successfully, compare global/page-tree/tagging context before changing page content. If native lookups identify one invalid relationship, propose a targeted change to that relationship with preservation checks. Do not rebuild the document, remove its tag tree, or graft large structures based only on stale-index counts. No repair algorithm or repair binary is included in this implementation.

## Outstanding validation

1. Reconfirm untouched October success and working failure on this exact hash/build, using recorded page-12 content.
2. Test derivative October-resaved, inverse and standalone controls. Check the serializer positive control first.
3. Obtain paired Acrobat-saved failed/successful outcomes and live logs where the native module can be built/loaded.
4. Compile the native module plus exact-signature assertions against the real installed Windows SDK and retain header/build manifests. Native source is not a compiled or tested plug-in.
5. Require FRO creation, Show In Tags navigation and save/reopen persistence before claiming success. Validate continuation pages and preserve the existing baseline structure, links, text and page appearance.

Current implementation tests exercise synthetic valid/broken associations and evidence safety. Generated controls and reports have static QA only. GUI behavior and native module host behavior remain untested on Windows. Static checks are not a substitute for Acrobat or a full PDF/UA review.

## Derivative-control static QA

The regenerated controls use pikepdf 10.18.2. Across all expected pages, rendered pixels at 96 DPI (PyMuPDF 1.26.6) and extracted text match the intended source pages: October for the resaved control, October except working page 12 for the inverse, and the respective original page 12 for each standalone control. Both 50-page October-based controls retain 268 reachable tags. The single-page controls have zero tags as designed. No catalog `/AF` association was introduced in any control. This removes that specific prior test-path confound; it does not prove serialization is behaviorally neutral in Acrobat. Detailed results are in `control_qa.json` in the evidence package.

**13 automated tests passed.** Native compilation, exact installed-header validation, Windows launcher use and all live Acrobat control tests remain pending.
