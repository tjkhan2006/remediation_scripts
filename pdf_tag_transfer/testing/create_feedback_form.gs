/**
 * PDF Tag Transfer tester feedback form generator.
 * Run createPdfTagTransferFeedbackForm in a standalone project at script.google.com.
 * Creates a Google Form and private response spreadsheet in the executing account.
 * Rerunning returns the same URLs, rather than creating duplicate forms.
 */
function createPdfTagTransferFeedbackForm() {
  const props = PropertiesService.getScriptProperties();
  const key = 'PDF_TAG_TRANSFER_FEEDBACK_V1';
  const saved = JSON.parse(props.getProperty(key) || '{}');
  let form = saved.formId ? FormApp.openById(saved.formId) : null;
  if (!form) {
    form = FormApp.create('PDF Tag Transfer — Build Testing & Feedback');
    saved.formId = form.getId();
    props.setProperty(key, JSON.stringify(saved));
  }
  if (saved.complete) return feedbackLinks_(form, saved.sheetId);

  // Retry an interrupted setup only while no feedback has been submitted.
  if (form.getResponses().length) {
    throw new Error('This form already has responses. Setup stopped to protect them. Edit the existing form instead: ' + form.getEditUrl());
  }
  while (form.getItems().length) form.deleteItem(0);
  form.setDescription(
    'Help improve PDF Tag Transfer. Submit one response per test session, even if you could not install or open the app. About 5–8 minutes.\n\n' +
    'Use a non-sensitive test copy. Do not paste confidential PDF content; redact screenshots and reports. This form does not upload PDFs or collect email automatically. Contact details are optional.\n\n' +
    'If you can, try: open the original and partially tagged PDFs; select tags and inspect outlines in all three previews; filter the tree; start/pause/step; undo; save a separate copy; reopen it in your PDF editor and try continued tagging. Mark anything you did not try as Not tested. A successful save is not proof of accessibility compliance.\n\n' +
    'Current build at form creation: 0.1.3. Enter the actual version from your app title below.'
  );
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setPublishingSummary(false);
  form.setAllowResponseEdits(true);
  form.setProgressBar(true);
  form.setShuffleQuestions(false);
  form.setConfirmationMessage('Thank you! Your feedback was recorded. If you hit another issue or test a different build, submit another response. Keep any test PDFs and reports locally in case follow-up is needed.');

  const text = (title, help, required) => {
    const item = form.addTextItem().setTitle(title).setRequired(Boolean(required));
    if (help) item.setHelpText(help);
    return item;
  };
  const paragraph = (title, help, required) => {
    const item = form.addParagraphTextItem().setTitle(title).setRequired(Boolean(required));
    if (help) item.setHelpText(help);
    return item;
  };
  const multiple = (title, choices, required) => form.addMultipleChoiceItem()
    .setTitle(title).setChoiceValues(choices).setRequired(Boolean(required));

  form.addSectionHeaderItem().setTitle('1. Your test setup');
  text('App version shown in the title bar', 'For example: 0.1.3. Enter Unknown if you could not launch it.', true);
  multiple('Operating system', ['Windows 11', 'Windows 10', 'macOS', 'Linux', 'Other / unknown'], true);
  text('PDF editor and version used for continued tagging', 'For example: Adobe Acrobat Pro and its version. Leave blank if not tested.', false);
  multiple('Your experience with PDF accessibility tagging', ['New to tagging', 'Some experience', 'Regular user', 'Advanced / specialist'], false);
  text('Number of pages in the test document', 'If known. Do not enter the document title or confidential information.', false)
    .setValidation(FormApp.createTextValidation().requireTextMatchesPattern('^[1-9][0-9]*$').setHelpText('Enter a positive whole number, or leave blank.').build());
  form.addCheckboxItem().setTitle('Which describe your PDF pair? Select all that apply.')
    .setChoiceValues(['Same page content and layout; only tagging differs', 'Some page content, layout or page counts differ', 'Contains tables', 'Contains images / figures', 'Scanned pages or OCR text', 'Contains links / annotations', 'Contains forms / reusable artwork', 'Not sure']).setRequired(false);

  form.addPageBreakItem().setTitle('2. What worked?');
  multiple('How far did you get?', [
    'Could not install or launch', 'Launched but could not complete Open / Analyze',
    'Opened the PDFs but could not start or complete transfer',
    'Transferred some or all pages but could not save',
    'Saved output; have not tried continued tagging',
    'Saved output, but continued tagging failed',
    'Saved output and successfully continued tagging'
  ], true);
  form.addGridItem().setTitle('Feature results')
    .setHelpText('Mark Not tested for steps you could not reach. A Needs review result is not automatically a bug; describe any unexpected result below.')
    .setRows(['Installation and launch', 'Open / Analyze', 'Viewing all three PDF previews', 'Selecting a tag and locating its bounding boxes', 'Tag tree, search and filters', 'Start, pause and step controls', 'Undo a transferred page', 'Save a separate PDF copy', 'Export the issue report'])
    .setColumns(['Worked', 'Partly worked', 'Did not work', 'Not tested']).setRequired(false);
  form.addGridItem().setTitle('Checks on the saved output')
    .setHelpText('Check what you actually verified. Use Unsure or Not tested if you cannot confirm. These answers are not an accessibility certification.')
    .setRows(['Original page appearance and text retained', 'Tag hierarchy and reading order retained', 'Alt text and other tag properties retained', 'Table cells, headers and attributes retained', 'Could add a tag in my PDF editor', 'New tag still worked after saving and reopening'])
    .setColumns(['Verified correct', 'Found an issue', 'Unsure', 'Not tested']).setRequired(false);
  multiple('How responsive was the app?', ['Responsive throughout', 'Some delays, but usable', 'Long delays or freezes', 'Crashed / closed unexpectedly', 'Not tested'], false);
  const bugRoute = form.addMultipleChoiceItem().setTitle('Did you encounter an error, unexpected result, or warning you need help understanding?').setRequired(true);

  const issues = form.addPageBreakItem().setTitle('3. Describe the main issue')
    .setHelpText('Report the most important issue from this test. You can submit another response for a separate issue.');
  multiple('How much did the issue affect your work?', [
    'Blocked testing or prevented continued work', 'Produced incorrect or missing output tags/content',
    'Needed a workaround', 'Minor inconvenience or confusing message', 'Warning only; unsure whether anything is wrong'
  ], true);
  paragraph('What did you do, what did you expect, and what happened instead?',
    'Include the steps in order, the button/control used, and page/tag type if known. Mention whether the issue happens every time.', true);
  paragraph('Exact error or warning text', 'Copy the full message if available. For a missing /Ref target, include its structure path. Otherwise leave blank.', false);
  paragraph('Was any work lost, changed, or missing?', 'Describe what you observed and any workaround. Say Unknown if you have not checked.', false);
  text('Optional link to a redacted screenshot or exported report',
    'Only share a link you intend the form owner to access. Do not upload a confidential PDF. If sharing a report, check it for sensitive file paths or metadata first.', false);

  const improvements = form.addPageBreakItem().setTitle('4. Improvements and follow-up');
  form.addScaleItem().setTitle('Overall, how easy was the app to use?')
    .setBounds(1,5).setLabels('Very difficult', 'Very easy').setRequired(false);
  paragraph('What is the single most useful change for the next build?',
    'For example: clearer warnings, more accurate content matches, better outlines, larger previews, or manual reassignment.', false);
  paragraph('What worked well and should be kept?', '', false);
  text('Contact email — optional', 'Enter only if you agree to follow-up about this test. Leave blank to provide feedback without contact details.', false)
    .setValidation(FormApp.createTextValidation().requireTextIsEmail().setHelpText('Enter a valid email address or leave blank.').build());
  bugRoute.setChoices([
    bugRoute.createChoice('Yes — describe it', issues),
    bugRoute.createChoice('No — go to improvements', improvements)
  ]);

  // Do not change sharing on the response spreadsheet; it is private by default.
  const sheet = saved.sheetId ? SpreadsheetApp.openById(saved.sheetId)
    : SpreadsheetApp.create('PDF Tag Transfer — Tester Responses');
  saved.sheetId = sheet.getId();
  props.setProperty(key, JSON.stringify(saved));
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());
  if (typeof form.supportsAdvancedResponderPermissions === 'function' && form.supportsAdvancedResponderPermissions()) {
    form.setPublished(true);
  }
  form.setAcceptingResponses(true);
  saved.complete = true;
  props.setProperty(key, JSON.stringify(saved));
  return feedbackLinks_(form, sheet.getId());
}

function feedbackLinks_(form, sheetId) {
  const result = {
    testerLink: form.getPublishedUrl(),
    editLink: form.getEditUrl(),
    responsesSheet: SpreadsheetApp.openById(sheetId).getUrl()
  };
  console.log('SHARE WITH TESTERS: ' + result.testerLink);
  console.log('OWNER ONLY — EDIT FORM: ' + result.editLink);
  console.log('OWNER ONLY — RESPONSES: ' + result.responsesSheet);
  return result;
}
