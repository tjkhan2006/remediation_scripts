# Native Acrobat diagnostic module: Windows validation required

**Status: implemented source module; no successful installed-header compile, `.api` build, signature validation, or live Acrobat run yet.** There are no Adobe SDK headers, Microsoft compiler or Acrobat installation in the attached Linux workspace. Do not rename these sources to `.api` or treat the static reports as native traces.

## Obtain the prerequisites

1. On the Windows computer running Acrobat 2026.002.22031 x64, use Adobe's [Getting Started / SDK downloads](https://developer.adobe.com/acrobat-pdfl-sdk/acrobat/gettingstarted). Choose the native **Acrobat SDK with Windows x64 plug-in headers**, rather than the cloud PDF Services SDK. Record the package name, release and download hash. Adobe's download flow may require sign-in/EULA review by you.
2. Install the compatible Visual Studio C++ workload and Windows SDK specified by that SDK's release notes. Adobe's older [x64 guide](https://opensource.adobe.com/dc-acrobat-sdk-docs/acrobatsdk/64bitdev.html) documents VS2019 16.4 as a minimum for its generation; that is not proof of compatibility with every current SDK.
3. Use a copy of the SDK's **BasicUI x64** sample, preserving its relative include/support-file layout. Adobe [recommends BasicUI and Starter](https://opensource.adobe.com/dc-acrobat-sdk-docs/library/plugin/Plugins_CreatingSimplePlug.html). Build the unmodified sample first to confirm that the SDK/toolchain and plug-in loading work.

## Integrate and build

1. Add `TagLinkAudit.cpp` and `SignatureChecks.cpp` to the copied BasicUI `.vcxproj`; add this folder to its include search path, or copy the `.cpp` files and `TagLinkAudit.h` into the copied sample directory. Compile as C++14 or later, x64.
2. In the sample's existing menu execute callback, include `TagLinkAudit.h` and call `NSSEAuditActiveDocument();` instead of the demonstration operation. Change its menu label to `NSSE Tag Link Audit (read-only)`. Use a unique sample extension name. Keep Adobe's supplied handshake, entry point, HFT acquisition and unload lifecycle. Do not invent alternate entry points from web snippets.
3. Ensure the sample imports PDSEdit read, PDFEdit read, PDModel, AcroView and Cos HFTs according to that SDK's sample/header conventions. Keep required HFT initialization; a compiling pointer expression alone does not initialize an HFT. Add `Comdlg32.lib` to linker inputs. Do not add document write functionality.
4. From PowerShell, run:

   ```powershell
   .\build.ps1 -SdkRoot "C:\path\to\AcrobatSDK" -Project "C:\path\to\copied\BasicUI.vcxproj"
   ```

   The script records installed header hashes/API declaration contexts and rebuilds the official project as x64. `SignatureChecks.cpp` compares return and parameter types for the core calls against the documented signatures. A failure is a compatibility finding; preserve the error and review the real declaration. Do not remove the assertions to force a build.
5. Retain `build/sdk-headers.json`, `build/build.txt`, `build/build.binlog` and `build/build-result.json`. Confirm the produced `.api` exists and hash it with `Get-FileHash -Algorithm SHA256`. Record the exact Acrobat build, Windows version, SDK package, compiler version and binary hash in the capture run manifest. A build is not successful until both source files actually compile.
6. Load the resulting `.api` only through your authorized Acrobat Pro plug-in deployment process in a test setup. No security settings are changed by these scripts. If organization policy blocks loading, record that condition and use the static before/after workflow while arranging approved access. No Reader-enabling or Adobe certification is claimed.

No automatic SDK-sample patcher is used: sample names/layouts/HFT imports can vary. The source is deliberately integrated with the installed official sample so its actual lifecycle can be reviewed.

## Capture live state

Run the menu command before the UI action, immediately after the UI action **before saving**, and again after saving/reopening. Choose a **new `.jsonl` file** each time. The module scans all pages and the reachable structure tree, and logs:

- document-local object references and actual structure `/ID` lookup results;
- reachable structure elements and native parent edges;
- PDE container tags, dictionary presence, MCIDs, and containing page/Form objects;
- native `PDSMCIDGetParent` results and `PDSMCGetParent` results for PDEContainer objects;
- SDK exception codes, partial traversal/truncation indicators and session timestamps.

A container without an MCID is logged without inventing an identifier. PDEBeginContainer objects receive MCID lookup only; they are not falsely passed as PDSMC. Form lookups use the Form stream, not the page. Native scans are bounded to avoid malformed-document hangs. Forms can be logged per invocation; static reports deduplicate their namespaces. No annotation appearance traversal is implemented. An incomplete traversal cannot prove a tag unreachable.

The module reads active in-memory state. It does not equate that state with the disk PDF hash. Pair each log with `run.json`, the corresponding static SHA-256, and whether the capture is before save or after reopening. The Acrobat build and SDK provenance are currently recorded in the run/build manifests, not automatically extracted by the module. `end` and the absence/presence of exception records must be reviewed before interpreting results.

There are no document creation/insertion/removal/save/content-commit calls. The only writes are to the chosen new log. Balanced page/PDE acquisition/release and SDK exception handlers are implemented. Runtime read-only behavior, resource cleanup and host compatibility still require validation in Acrobat; source inspection alone cannot establish them.
