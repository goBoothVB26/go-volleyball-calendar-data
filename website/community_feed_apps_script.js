/**
 * Community events feed: serves the Google Form responses sheet as JSON
 * so the scraper can ingest submitted events. No service account or GCP
 * project needed -- the web app runs as you and the sheet stays private.
 *
 * SETUP (about 3 minutes):
 *  1. Open the FORM RESPONSES spreadsheet -> Extensions -> Apps Script.
 *  2. Delete the sample code, paste this file, save.
 *  3. Deploy -> New deployment -> type: Web app.
 *       - Execute as: Me
 *       - Who has access: Anyone
 *     Deploy, authorize, and COPY THE WEB APP URL.
 *  4. Put that URL in scraper/adapters/community.py (COMMUNITY_FEED_URL)
 *     or set the COMMUNITY_FEED_URL environment variable.
 *
 * The URL is a long unguessable token; only someone holding it can read
 * the feed, and it exposes exactly what the calendar needs. If your form
 * collects submitter emails, the scraper ignores that column entirely.
 */

function doGet() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  // getDisplayValues(): strings exactly as shown in the sheet, so dates
  // and times arrive as typed ("7/26/2026", "6:00 PM") instead of as
  // timezone-shifted ISO datetimes.
  var values = sheet.getDataRange().getDisplayValues();
  return ContentService
    .createTextOutput(JSON.stringify({ values: values }))
    .setMimeType(ContentService.MimeType.JSON);
}
