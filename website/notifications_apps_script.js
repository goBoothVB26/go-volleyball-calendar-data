/**
 * Event notification signups + reminder emails for the volleyball calendar.
 *
 * What it does:
 *  - doPost: receives "Sign up for Notifications" submissions from the
 *    website widget, appends them to a Google Sheet, and immediately
 *    emails a signup confirmation (same look as the reminder emails).
 *  - sendReminders: run hourly by a trigger; emails each subscriber
 *    ~5 days and ~24 hours before their event starts.
 *
 * ONE-TIME SETUP (about 10 minutes):
 *  1. Go to sheets.google.com -> create a blank spreadsheet named e.g.
 *     "Volleyball Event Signups". Add a header row in row 1:
 *     signed_up | email | uid | title | start | club | url | sent_5day | sent_24hr | extra
 *  2. In the sheet: Extensions -> Apps Script. Delete the sample code,
 *     paste this entire file, and save.
 *  3. Click "Deploy" -> "New deployment" -> type: Web app.
 *       - Execute as: Me
 *       - Who has access: Anyone
 *     Click Deploy, authorize it, and COPY THE WEB APP URL.
 *  4. Paste that URL into the widget's NOTIFY_ENDPOINT (in the
 *     Squarespace Code block) and republish the page. Bookmark icons
 *     appear once the URL is set.
 *  5. Back in Apps Script: left sidebar clock icon (Triggers) ->
 *     Add Trigger -> function sendReminders -> time-driven -> hour timer
 *     -> every hour. Save.
 *
 * Notes:
 *  - Emails send from the Google account that owns the script.
 *  - Free Gmail accounts can send ~100 emails/day via Apps Script
 *    (Workspace accounts ~1500/day). Plenty for a community calendar,
 *    but worth knowing if signups get big.
 */

var REMINDER_WINDOWS = [
  // beforeLabel is used in the confirmation email ("we'll email you
  // 5 days before..."); label is used in the reminder email itself
  // ("...starts in 5 days").
  { hoursBefore: 120, column: 8, label: "in 5 days", beforeLabel: "5 days before" },   // sent_5day
  { hoursBefore: 24, column: 9, label: "in 24 hours", beforeLabel: "24 hours before" }, // sent_24hr
];

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  if (!data.email || !data.uid || !data.start) {
    return ContentService.createTextOutput("missing fields");
  }
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

  // Skip exact duplicates (same email + same event) -- no duplicate
  // confirmation email either, since they already got one.
  var rows = sheet.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (rows[i][1] === data.email && rows[i][2] === data.uid) {
      return ContentService.createTextOutput("already signed up");
    }
  }

  sheet.appendRow([
    new Date(), data.email, data.uid, data.title || "",
    data.start, data.club || "", data.url || "", "", "",
    // Column 10 "extra": card data (tags, color, logo, location) as
    // JSON, used to render the event card in the reminder/confirmation
    // emails.
    data.extra ? JSON.stringify(data.extra) : "",
  ]);
  addToMailingList(data.email);
  sendSignupConfirmation(data);
  return ContentService.createTextOutput("ok");
}

/**
 * Sent immediately on signup -- same card-style email as the reminders,
 * confirming the signup and explaining when the actual reminders will
 * arrive.
 */
function sendSignupConfirmation(data) {
  var extra = data.extra || {};
  var start = new Date(data.start);
  if (isNaN(start)) return;  // malformed date -- skip rather than send garbage

  var whenText = Utilities.formatDate(start, Session.getScriptTimeZone(), "EEEE, MMMM d 'at' h:mm a");
  var end = extra.end ? new Date(extra.end) : null;
  if (!end || isNaN(end)) end = new Date(start.getTime() + 2 * 36e5);  // default 2h

  var beforeLabels = REMINDER_WINDOWS.map(function (w) { return w.beforeLabel; });
  var scheduleText = beforeLabels.length > 1
    ? beforeLabels.slice(0, -1).join(", ") + " and " + beforeLabels[beforeLabels.length - 1]
    : (beforeLabels[0] || "");

  // Wording is deliberately "you'll be reminded", never "confirmed" or
  // "registered" -- this only opts someone into reminder emails, it is
  // NOT an RSVP or event registration, and the copy (plus the standalone
  // note below) makes that distinction explicit rather than implying
  // more than actually happened.
  var subject = "You'll be reminded about \"" + data.title + "\"";

  var body =
    "Hi!\n\nYou'll be reminded! We'll email you " + scheduleText + " \"" + data.title + "\"" +
    (data.club ? " (" + data.club + ")" : "") + " starts:\n\n" + whenText +
    (extra.location ? "\nLocation: " + extra.location : "") +
    "\n\nNote: this sets up email reminders only -- it does not register you" +
    " for the event. Be sure to register separately if the event requires it." +
    (data.url ? "\n\nDetails / registration: " + data.url : "") +
    "\n\nSee you on the court,\nYour Greater Orlando Community Member" +
    "\n\n-- \nYou received this because you signed up for reminders" +
    " for this event on our community calendar.";

  var introHtml =
    "<p>Hi!</p>" +
    "<p>You'll be reminded! We'll email you <b>" + htmlEsc(scheduleText) + "</b> " +
    "<b>&ldquo;" + htmlEsc(data.title) + "&rdquo;</b>" +
    (data.club ? " (" + htmlEsc(data.club) + ")" : "") + " starts:</p>" +
    '<p style="color:#0057b8; font-weight:bold; font-size:13px;">Note: this sets up' +
    " email reminders only -- it does not register you for the event. Be sure to" +
    " register separately if the event requires it.</p>";

  MailApp.sendEmail(data.email, subject, body, {
    htmlBody: buildEventCardEmail(data.title, data.club, data.url, whenText, introHtml, extra),
    attachments: [buildInviteIcs(data.title, start, end, extra.location, data.url, data.uid, data.email, 0)],
  });
}

/**
 * Master mailing list: a second sheet ("Mailing List") holding each
 * distinct email once, with the date it first signed up. Created
 * automatically on first use; safe to sort or add columns to.
 */
function addToMailingList(email) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var list = ss.getSheetByName("Mailing List");
  if (!list) {
    list = ss.insertSheet("Mailing List");
    list.appendRow(["email", "first_signed_up"]);
  }
  var normalized = String(email).trim().toLowerCase();
  var existing = list.getDataRange().getValues();
  for (var i = 1; i < existing.length; i++) {
    if (String(existing[i][0]).trim().toLowerCase() === normalized) return;
  }
  list.appendRow([normalized, new Date()]);
}

/**
 * One-time backfill: run this manually once (Run > backfillMailingList
 * in the Apps Script editor) to add everyone who signed up BEFORE this
 * feature existed. New signups are added automatically by doPost.
 */
function backfillMailingList() {
  var rows = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0].getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (rows[i][1]) addToMailingList(rows[i][1]);
  }
}

function sendReminders() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var rows = sheet.getDataRange().getValues();
  var now = new Date();

  for (var i = 1; i < rows.length; i++) {
    var email = rows[i][1], title = rows[i][3], startRaw = rows[i][4];
    var club = rows[i][5], url = rows[i][6];
    var start = startRaw instanceof Date ? startRaw : new Date(String(startRaw));
    if (!email || isNaN(start)) continue;

    var hoursUntil = (start - now) / 36e5;
    if (hoursUntil <= 0) continue;  // event already started

    for (var w = 0; w < REMINDER_WINDOWS.length; w++) {
      var win = REMINDER_WINDOWS[w];
      var alreadySent = rows[i][win.column - 1];
      if (alreadySent || hoursUntil > win.hoursBefore) continue;

      var extra = {};
      try { extra = JSON.parse(rows[i][9] || "{}"); } catch (err) {}

      var subject = "Reminder: " + title + " is " + win.label;
      var whenText = Utilities.formatDate(
        start, Session.getScriptTimeZone(), "EEEE, MMMM d 'at' h:mm a");

      // Plain-text fallback for clients that don't render HTML
      var body =
        "Hi!\n\nThis is your reminder that \"" + title + "\"" +
        (club ? " (" + club + ")" : "") +
        " starts " + win.label + ":\n\n" + whenText +
        (extra.location ? "\nLocation: " + extra.location : "") +
        (url ? "\n\nDetails / registration: " + url : "") +
        "\n\nSee you on the court,\nYour Greater Orlando Community Member" +
        "\n\n-- \nYou received this because you signed up for notifications" +
        " for this event on our community calendar.";

      var end = extra.end ? new Date(String(extra.end)) : null;
      if (!end || isNaN(end)) end = new Date(start.getTime() + 2 * 36e5);  // default 2h

      MailApp.sendEmail(email, subject, body, {
        htmlBody: buildReminderHtml(title, club, url, whenText, win.label, extra),
        // A real calendar invite: Gmail (and most clients) render their
        // native "Add to calendar / RSVP" widget at the top of the email.
        // sequence w+1: 5-day reminder = revision 1, 24-hour = revision 2
        // (the signup confirmation was revision 0)
        attachments: [buildInviteIcs(title, start, end, extra.location, url, rows[i][2], email, w + 1)],
      });
      sheet.getRange(i + 1, win.column).setValue(new Date());
      rows[i][win.column - 1] = new Date();  // don't double-send within this run
    }
  }
}

/**
 * iCalendar invite attachment. METHOD:REQUEST + an ORGANIZER/ATTENDEE
 * pair is what makes Gmail show its native calendar chip on the email.
 *
 * `sequence` is the iCalendar revision number for this event: the
 * confirmation ships revision 0, the 5-day reminder revision 1, the
 * 24-hour reminder revision 2. Same UID + a HIGHER sequence is what
 * tells calendar clients "update the event you already have" -- without
 * it, a second same-UID invite is ambiguous and Gmail imports it as a
 * duplicate event instead of an update.
 */
function buildInviteIcs(title, start, end, location, url, uid, email, sequence) {
  function fmt(d) {
    return Utilities.formatDate(d, "UTC", "yyyyMMdd'T'HHmmss'Z'");
  }
  function icsEsc(s) {
    return String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;")
                          .replace(/,/g, "\\,").replace(/\n/g, "\\n");
  }
  var organizer = Session.getEffectiveUser().getEmail();
  var ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//GOVB Community Calendar//EN",
    "METHOD:REQUEST",
    "BEGIN:VEVENT",
    "UID:" + icsEsc(uid || title) + "@govb-calendar",
    "DTSTAMP:" + fmt(new Date()),
    "DTSTART:" + fmt(start),
    "DTEND:" + fmt(end),
    "SUMMARY:" + icsEsc(title),
    location ? "LOCATION:" + icsEsc(location) : null,
    url ? "DESCRIPTION:" + icsEsc("Details / registration: " + url) : null,
    "ORGANIZER;CN=GOVB Community Calendar:mailto:" + organizer,
    "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:" + email,
    "SEQUENCE:" + (sequence || 0),
    "STATUS:CONFIRMED",
    "END:VEVENT",
    "END:VCALENDAR",
  ].filter(function (line) { return line !== null; }).join("\r\n");

  return Utilities.newBlob(ics, "text/calendar; charset=UTF-8; method=REQUEST", "invite.ics");
}

function htmlEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * Shared card-style email body used by BOTH the signup confirmation and
 * the reminder emails: tag/filter chips lined above the same event card
 * the calendar renders (club-colored left ribbon, logo, title, club,
 * date/time, location, register button). All styles are inline -- email
 * clients strip <style> blocks. `introHtml` is the only part that
 * differs between the two email types (confirmation vs. reminder
 * wording) -- it's raw HTML, so callers must escape any interpolated
 * values themselves via htmlEsc().
 */
function buildEventCardEmail(title, club, url, whenText, introHtml, extra) {
  var color = extra.color || "#0057b8";
  var tags = extra.tags || [];

  var chips = tags.map(function (t) {
    return '<span style="display:inline-block; background:#eef3fa; color:#0057b8;' +
           ' border-radius:10px; padding:3px 11px; font-size:12px;' +
           ' margin:0 5px 6px 0; font-family:Arial,Helvetica,sans-serif;">' +
           htmlEsc(t) + "</span>";
  }).join("");

  var mapsLink = extra.location
    ? "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(extra.location)
    : "";

  var logoCell = extra.logo
    ? '<td valign="top" style="padding:16px 0 16px 16px; width:84px;">' +
      '<img src="' + htmlEsc(extra.logo) + '" width="72" alt="" ' +
      'style="display:block; max-width:72px; height:auto;"></td>'
    : "";

  return (
    '<div style="font-family:Arial,Helvetica,sans-serif; color:#222; font-size:14px;' +
    ' max-width:520px; margin:0 auto;">' +
      introHtml +

      // Tag/filter chips lined above the card
      '<div style="margin:0 0 8px;">' + chips + "</div>" +

      // The event card: white, rounded, club-colored left ribbon
      '<table cellpadding="0" cellspacing="0" width="100%" style="background:#ffffff;' +
      ' border:1px solid #e6e6e6; border-left:6px solid ' + htmlEsc(color) + ';' +
      ' border-radius:14px; box-shadow:0 4px 14px rgba(0,0,0,0.10);"><tr>' +
        logoCell +
        '<td valign="top" style="padding:16px;">' +
          '<div style="font-size:17px; font-weight:bold; line-height:1.35;">' + htmlEsc(title) + "</div>" +
          '<div style="color:#666; margin-top:2px;">' + htmlEsc(club) + "</div>" +
          '<div style="color:#333; margin-top:8px;">&#128197; ' + htmlEsc(whenText) + "</div>" +
          (extra.location
            ? '<div style="margin-top:4px;">&#128205; <a href="' + htmlEsc(mapsLink) +
              '" style="color:#0057b8;">' + htmlEsc(extra.location) + "</a></div>"
            : "") +
          (url
            ? '<a href="' + htmlEsc(url) + '" style="display:inline-block; margin-top:14px;' +
              ' background:#0057b8; color:#ffffff; text-decoration:none;' +
              ' padding:9px 18px; border-radius:8px; font-size:14px; font-weight:bold;">' +
              "More info / Register</a>"
            : "") +
        "</td>" +
      "</tr></table>" +

      // Sign-off: GOVB logo to the left of (and level with) the two lines
      '<table cellpadding="0" cellspacing="0" style="margin-top:18px;"><tr>' +
        '<td valign="middle" style="padding-right:10px;">' +
          '<img src="https://raw.githubusercontent.com/goBoothVB26/go-volleyball-calendar-data/main/logos/govb.png"' +
          ' width="44" alt="GOVB" style="display:block; max-width:44px; height:auto;"></td>' +
        '<td valign="middle" style="font-family:Arial,Helvetica,sans-serif; font-size:14px;' +
        ' color:#222; line-height:1.5;">See you on the court,<br>' +
        "Your Greater Orlando Community Member</td>" +
      "</tr></table>" +
      '<p style="color:#999; font-size:11px; margin-top:22px;">You received this because' +
      " you signed up for notifications for this event on our community calendar.</p>" +
    "</div>"
  );
}

/**
 * Reminder email: thin wrapper around buildEventCardEmail with the
 * "starts in 5 days / 24 hours" intro wording.
 */
function buildReminderHtml(title, club, url, whenText, windowLabel, extra) {
  var introHtml =
    "<p>Hi!</p>" +
    "<p>This is your reminder that <b>&ldquo;" + htmlEsc(title) + "&rdquo;</b>" +
    (club ? " (" + htmlEsc(club) + ")" : "") +
    " starts <b>" + htmlEsc(windowLabel) + "</b>:</p>";
  return buildEventCardEmail(title, club, url, whenText, introHtml, extra);
}
