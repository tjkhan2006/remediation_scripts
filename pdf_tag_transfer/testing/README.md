# Create the Google tester feedback form

This folder contains a Google Apps Script that creates a Google Form and links it
to a new response spreadsheet in **your** Google account. It does not change the
PDF Tag Transfer app. The form has not been created until you run the script.

1. Open https://script.google.com/home/start and create a **New project**.
2. Replace all of `Code.gs` with `create_feedback_form.gs` from this folder.
3. Select **createPdfTagTransferFeedbackForm** in the function dropdown and click
   **Run**. Approve access to Forms and Sheets for this script if you trust the code.
   You do not need to deploy a web app.
4. Open the **Execution log**. It prints three links: the tester form, the form
   editor, and the response spreadsheet. Share **only the tester link**.
5. Open the form editor and check **Publish / Manage responder access** (or **Send**
   in older Forms). Ensure your intended testers can respond. Workspace policies
   may restrict external respondents. Verify from an incognito browser or a tester
   account before distributing it. Submit one trial response and confirm it appears
   in both the form's Responses tab and the linked spreadsheet.

The script does not automatically collect Google account email, does not limit
people to one response, and disables response-summary publication. The optional
contact question asks permission for follow-up. No PDF or screenshot uploads are
required; evidence links are optional. The responses spreadsheet is not shared by
the script. Google Workspace policies may still require sign-in or restrict access.
Do not share the owner edit/spreadsheet links with testers.

Rerunning the function returns the same links. If setup is interrupted, rerunning
rebuilds the unfinished form only if no responses have been submitted. Existing
responses are never deleted by the script. To intentionally create an independent
form, use a new Apps Script project.

## What testers report

- Actual build version, operating system, PDF editor, experience and PDF features.
- How far they got, including installation and Open / Analyze failures.
- Feature outcomes for previews, outlines, filters, controls, saving and reports.
- Whether output appearance, tags, tables and continued tagging were verified.
- Optional issue branch with severity, reproduction steps, expected/actual results,
  exact errors, possible lost work, and optional redacted evidence links.
- Ease of use, the top requested improvement, what to keep and optional follow-up.

Most questions are optional so a tester who gets blocked early can still report
useful feedback. The issue branch is skipped when no problem was encountered.
The form description identifies 0.1.3 as the build current when the script was
prepared; responses always ask for the actual version being tested.

## Prioritizing responses

Filter the response sheet by build version first. Investigate lost/incorrect
output and blocked continued tagging before cosmetic requests. Group repeated
errors by their message and workflow stage. Treat unsupported-content warnings
separately from wrong output, but use reports to decide which limitations to
address next. Do not classify a successful save as proven accessibility.

## Validation status

Syntax and local simulated Forms/Sheets execution are checked during development,
including branching, private response settings and repeat-run behavior. Live Google
authorization, publishing, and response collection need the trial submission above.
