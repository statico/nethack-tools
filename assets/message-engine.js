/* ==========================================================================
   message-engine.js — search/filter/highlight logic for the message lookup
   tool. Pure logic, zero DOM access.

   data/messages.json entries carry text_norm/explanation_norm fields
   already run through gen-messages.py's norm_text() (lowercase, HTML tags
   stripped, everything but [a-z0-9 ] blanked, whitespace collapsed). A
   typed query has to go through the *same* transform to match them, so
   normalize() here is a deliberate port of that Python function rather
   than a fresh generic "search normalize".

   Loadable as a plain <script> (defines window.MessageEngine) or via
   require() in node (module.exports).
   ========================================================================== */

var MessageEngine = (function () {
  'use strict';

  function normalize(s) {
    return String(s || '')
      .replace(/<[^>]*>/g, ' ')
      .toLowerCase()
      .replace(/[^a-z0-9 ]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  var STATUS_BADGE = {
    present: { label: 'present', cls: 'b-green' },
    absent: { label: 'absent', cls: 'b-red' },
    unverified: { label: 'unverified', cls: 'b-yellow' }
  };

  function statusBadge(status) {
    return STATUS_BADGE[status] || { label: status || 'unknown', cls: 'b-dim' };
  }

  /* Match rank: 0 = query occurs in the message text itself (most relevant),
     1 = query occurs only in the explanation. null = no match at all. */
  function matchRank(entry, normQuery) {
    if (!normQuery) return null;
    if ((entry.text_norm || '').indexOf(normQuery) >= 0) return 0;
    if ((entry.explanation_norm || '').indexOf(normQuery) >= 0) return 1;
    return null;
  }

  function versionOk(entry, version) {
    if (version === 'any') return true;
    var v = entry.versions && entry.versions[version];
    return !!v && v.status === 'present';
  }

  /* Filters `entries` by query + version, sorted by match rank (text hits
     before explanation-only hits) with original array order as the
     tiebreaker so results don't jitter as you type. Caps at `limit` (0 or
     omitted = no cap) and reports how many real matches were dropped, so a
     truncation is always shown rather than silently hidden. */
  function search(entries, query, opts) {
    opts = opts || {};
    var version = opts.version || 'any';
    var limit = opts.limit || 0;
    var normQuery = normalize(query);

    if (!normQuery) return { results: [], total: 0, truncated: false };

    var hits = [];
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (!versionOk(e, version)) continue;
      var rank = matchRank(e, normQuery);
      if (rank === null) continue;
      hits.push({ entry: e, rank: rank, i: i });
    }
    hits.sort(function (a, b) {
      if (a.rank !== b.rank) return a.rank - b.rank;
      return a.i - b.i;
    });

    var total = hits.length;
    var truncated = limit > 0 && total > limit;
    if (truncated) hits = hits.slice(0, limit);

    return { results: hits.map(function (h) { return h.entry; }), total: total, truncated: truncated };
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /* Wraps case-insensitive occurrences of the raw (un-normalized) query in
     <mark>. Matching here is intentionally simpler than the normalized
     search match — it only has to look right on the already-matched text,
     not decide whether something matches. A query with no literal overlap
     with the display text (e.g. matching only through normalization
     stripping punctuation) safely highlights nothing. */
  function highlight(text, query) {
    var q = String(query || '').trim();
    if (!q) return escapeHtml(text);
    var re = new RegExp('(' + escapeRegExp(escapeHtml(q)) + ')', 'ig');
    return escapeHtml(text).replace(re, '<mark>$1</mark>');
  }

  var API = {
    normalize: normalize,
    statusBadge: statusBadge,
    matchRank: matchRank,
    versionOk: versionOk,
    search: search,
    escapeHtml: escapeHtml,
    highlight: highlight
  };
  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = MessageEngine;
if (typeof window !== 'undefined') window.MessageEngine = MessageEngine;
