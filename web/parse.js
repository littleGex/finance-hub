"use strict";
/* Amount parsing shared by the page (window.parseAmount) and the Node tests (module.exports). */
(function (root) {
  /**
   * Accepts German and English money input:
   *   "1.234,56" / "12,50"  -> comma is the decimal mark
   *   "1.500" / "1.234.567" -> dots in groups of three are thousands separators
   *   "12.50" / "1,234.56"  -> English
   * Returns NaN for anything that isn't a number.
   */
  function parseAmount(v) {
    let s = String(v).trim().replace(/\s|€/g, "");
    if (s === "") return NaN;
    const lastDot = s.lastIndexOf("."), lastComma = s.lastIndexOf(",");
    if (lastDot >= 0 && lastComma >= 0) {
      // Both present: whichever comes last is the decimal mark.
      s = lastComma > lastDot ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    } else if (lastComma >= 0) {
      s = s.replace(",", ".");
    } else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) {
      s = s.replace(/\./g, "");
    }
    return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : NaN;
  }
  root.parseAmount = parseAmount;
  if (typeof module === "object" && module.exports) module.exports = { parseAmount };
})(typeof window !== "undefined" ? window : globalThis);
