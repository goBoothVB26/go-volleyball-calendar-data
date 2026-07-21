/**
 * Site-wide dark mode sync. Paste this into Squarespace's Settings ->
 * Advanced -> Code Injection -> HEADER (site-wide, not a page Code
 * block) so every page -- present and future -- picks up whichever
 * theme was chosen on the calendar page (or any page with the toggle
 * widget below).
 *
 * How it works: the calendar widget stores the visitor's choice in
 * localStorage under "vbcalTheme" ("dark"/"light"), plus a timestamp
 * under "vbcalThemeTS". localStorage is shared across every page on
 * your domain, so this script reads that same key on every page load
 * and toggles body.vb-dark-page, the same class your site-wide Custom
 * CSS dark-mode rules already key off. No visible UI here -- it just
 * keeps every page in sync with whatever theme was set elsewhere.
 *
 * The choice EXPIRES 5 minutes after the last time any tab was
 * actively using the site: storedTheme() below checks the timestamp on
 * every read and self-clears once stale, so a choice from days ago
 * never overrides a fresh visit's device setting, while reopening a
 * tab closed moments ago still honors it. The timestamp is refreshed
 * on load and periodically while a page stays open.
 *
 * IMPORTANT: because Google Forms/embeds render in a cross-origin
 * iframe, this script (and your Custom CSS) can only darken the
 * SQUARESPACE PAGE around an embedded form -- it cannot restyle the
 * form's own content inside the iframe. Google Forms doesn't offer a
 * dark theme, so an embedded form will always show its normal white
 * background regardless of the surrounding page's theme.
 */
(function () {
  var THEME_TTL_MS = 5 * 60 * 1000;

  function prefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function storedTheme() {
    var stored = localStorage.getItem("vbcalTheme");
    var ts = +localStorage.getItem("vbcalThemeTS") || 0;
    if (stored && Date.now() - ts > THEME_TTL_MS) {
      localStorage.removeItem("vbcalTheme");
      localStorage.removeItem("vbcalThemeTS");
      return null;
    }
    return stored;
  }
  function touchThemeTS() {
    if (localStorage.getItem("vbcalTheme")) localStorage.setItem("vbcalThemeTS", String(Date.now()));
  }
  function currentDark() {
    var stored = storedTheme();
    return stored ? stored === "dark" : prefersDark();
  }
  function apply(dark) {
    document.body.classList.toggle("vb-dark-page", dark);
  }

  apply(currentDark());
  touchThemeTS();
  document.addEventListener("visibilitychange", function () { if (!document.hidden) touchThemeTS(); });
  setInterval(touchThemeTS, 60000);

  // Follow live device-theme changes for visitors who haven't chosen
  // (or whose choice has since expired)
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function (e) {
      if (!storedTheme()) apply(e.matches);
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
  }

  // If the visitor toggles theme in another open tab (e.g. the
  // calendar page), this tab updates instantly too.
  window.addEventListener("storage", function (e) {
    if (e.key === "vbcalTheme") apply(currentDark());
  });
})();
