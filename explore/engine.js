/* Disaster Data — Explorer engine core.
   Three pieces, no dependencies:
     Store  — one state object, subscribe/notify, URL serialization
     Anim   — rAF loop, easing matching the site's cubic-bezier(.22,1,.36,1), cancellable timers
     Query  — typed-array indexes over the county-event table + an incremental
              "cumulative totals as of day N" accumulator (the piece playback depends on)
   Everything hangs off window.DD. */
(function (root) {
  'use strict';

  /* ══ Anim ══════════════════════════════════════════════════════════════ */

  var reduceMotion = !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* quintic-out closely tracks the site's cubic-bezier(.22,1,.36,1): max deviation 1.1%,
     versus 9.9% for the more familiar expo-out. Pure multiplication, no Math.pow. */
  function easeOut(t) { var u = 1 - t; return 1 - u * u * u * u * u; }
  function easeOutExpo(t) { return easeOut(t); }          /* back-compat alias */
  function easeOutCubic(t) { var u = 1 - t; return 1 - u * u * u; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }

  /* One shared rAF loop. Subscribers get (dtMs, nowMs); returning nothing keeps them alive. */
  function Ticker() {
    this._subs = [];
    this._raf = 0;
    this._last = 0;
    this._running = false;
  }
  Ticker.prototype.add = function (fn) {
    if (this._subs.indexOf(fn) < 0) this._subs.push(fn);
    this.start();
    return fn;
  };
  Ticker.prototype.remove = function (fn) {
    var i = this._subs.indexOf(fn);
    if (i >= 0) this._subs.splice(i, 1);
    if (!this._subs.length) this.stop();
  };
  Ticker.prototype.start = function () {
    if (this._running) return;
    this._running = true;
    this._last = (root.performance && performance.now()) || Date.now();
    var self = this;
    (function frame(now) {
      if (!self._running) return;
      self._raf = requestAnimationFrame(frame);
      now = now || ((root.performance && performance.now()) || Date.now());
      var dt = now - self._last;
      if (dt > 250) dt = 250;               /* tab was backgrounded — don't fast-forward */
      self._last = now;
      var subs = self._subs.slice();
      for (var i = 0; i < subs.length; i++) subs[i](dt, now);
    })();
  };
  Ticker.prototype.stop = function () {
    this._running = false;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
  };

  /* Cancellable timer registry — generalizes leadtime.html's later()/clearSeq(). */
  function Seq() { this._t = []; }
  Seq.prototype.later = function (fn, ms) { var id = setTimeout(fn, ms); this._t.push(id); return id; };
  Seq.prototype.clear = function () { this._t.forEach(clearTimeout); this._t = []; };

  /* Tween a scalar over time. Returns a stop() handle. */
  function tween(ticker, from, to, ms, ease, onUpdate, onDone) {
    if (reduceMotion || ms <= 0) { onUpdate(to); if (onDone) onDone(); return function () {}; }
    var elapsed = 0;
    function step(dt) {
      elapsed += dt;
      var t = clamp(elapsed / ms, 0, 1);
      onUpdate(lerp(from, to, ease(t)));
      if (t >= 1) { ticker.remove(step); if (onDone) onDone(); }
    }
    ticker.add(step);
    return function () { ticker.remove(step); };
  }

  /* ══ Store ═════════════════════════════════════════════════════════════ */

  function Store(initial) {
    this.state = initial;
    this._subs = [];
    this._queued = false;
  }
  Store.prototype.subscribe = function (fn) {
    this._subs.push(fn);
    return function () { var i = this._subs.indexOf(fn); if (i >= 0) this._subs.splice(i, 1); }.bind(this);
  };
  /* Merge a patch and notify. `channels` names what changed so views can skip work. */
  Store.prototype.set = function (patch, channels) {
    var changed = false, k;
    for (k in patch) {
      if (patch[k] !== this.state[k]) { this.state[k] = patch[k]; changed = true; }
    }
    if (changed || channels) this._notify(channels || Object.keys(patch));
    return changed;
  };
  Store.prototype._notify = function (channels) {
    var subs = this._subs.slice();
    for (var i = 0; i < subs.length; i++) subs[i](this.state, channels);
  };

  /* ══ Query ═════════════════════════════════════════════════════════════ */

  /* Decodes the generated payload into typed arrays and builds:
       - day index (first event offset per day) for O(1) day slicing
       - per-county cumulative snapshots every SNAP_DAYS so random seeks are cheap
     All filtering is expressed as a predicate over (type, hazard) bitmasks, so a
     filter change only invalidates the accumulator, never the base arrays. */

  var SNAP_DAYS = 365;

  function Query(payload) {
    var cols = payload.cols, n = cols.fips.length;
    this.n = n;
    this.epoch = payload.epoch;
    this.maxDay = payload.days;
    this.fipsList = payload.fips;
    this.labels = payload.labels;
    this.hazards = payload.hazards;
    this.types = payload.types;
    this.decls = payload.decls;
    this.nCounty = payload.fips.length;

    /* columns → typed arrays (fips fits u16: 3,241 counties) */
    var day = new Int32Array(n), fips = new Uint16Array(n),
        type = new Uint8Array(n), haz = new Uint8Array(n), decl = new Uint16Array(n);
    var d = 0;
    for (var i = 0; i < n; i++) {
      d += cols.dayDelta[i];
      day[i] = d;
      fips[i] = cols.fips[i];
      type[i] = cols.type[i];
      haz[i] = cols.haz[i];
      decl[i] = cols.decl[i];
    }
    this.day = day; this.fips = fips; this.type = type; this.haz = haz; this.decl = decl;

    /* dayStart[k] = first event index with day >= k  (length maxDay+2) */
    var dayStart = new Int32Array(this.maxDay + 2);
    var cur = 0;
    for (var k = 0; k <= this.maxDay; k++) {
      while (cur < n && day[cur] < k) cur++;
      dayStart[k] = cur;
    }
    dayStart[this.maxDay + 1] = n;
    this.dayStart = dayStart;

    this._snapAll = null;      /* snapshots for the unfiltered case (built lazily) */
    this._mask = null;
    this._counts = new Uint16Array(this.nCounty);
    this._cursorDay = -1;
    this._snaps = null;
    this._total = 0;
    this._snapTotals = null;
  }

  /* Build the accept-mask for the current filters. null = accept everything.
     `geo` is an optional Uint8Array over counties (1 = in scope) — the geographic
     cross-filter, applied uniformly so every aggregation below is scope-aware. */
  Query.prototype.setFilter = function (typeSet, hazSet, geo) {
    var allTH = (!typeSet || typeSet.size === this.types.length) &&
                (!hazSet || hazSet.size === this.hazards.length);
    if (allTH) { this._mask = null; }
    else {
      var tm = new Uint8Array(this.types.length), hm = new Uint8Array(this.hazards.length), i;
      for (i = 0; i < tm.length; i++) tm[i] = (!typeSet || typeSet.has(this.types[i])) ? 1 : 0;
      for (i = 0; i < hm.length; i++) hm[i] = (!hazSet || hazSet.has(this.hazards[i])) ? 1 : 0;
      this._mask = { t: tm, h: hm };
    }
    this._geo = geo || null;
    this._snaps = null;                     /* filters changed → snapshots invalid */
    this._snapTotals = null;
    this._cursorDay = -1;
    return this;
  };

  /* Build a county scope mask: a 2-digit state FIPS prefix, or a single county index. */
  Query.prototype.geoMask = function (spec) {
    if (!spec) return null;
    var m = new Uint8Array(this.nCounty), i, hit = 0;
    if (spec.fipsIdx != null && spec.fipsIdx >= 0) {
      m[spec.fipsIdx] = 1; hit = 1;
    } else if (spec.state) {
      for (i = 0; i < this.fipsList.length; i++) {
        if (this.fipsList[i].slice(0, 2) === spec.state) { m[i] = 1; hit++; }
      }
    }
    return hit ? m : null;
  };

  Query.prototype.accepts = function (i) {
    var m = this._mask;
    if (m && (m.t[this.type[i]] !== 1 || m.h[this.haz[i]] !== 1)) return false;
    if (this._geo && this._geo[this.fips[i]] !== 1) return false;
    return true;
  };

  /* Snapshots of the cumulative county counts every SNAP_DAYS, under current filters. */
  Query.prototype._buildSnaps = function () {
    var nSnap = Math.floor(this.maxDay / SNAP_DAYS) + 1;
    var snaps = new Array(nSnap), totals = new Int32Array(nSnap);
    var acc = new Uint16Array(this.nCounty), total = 0;
    var i = 0, s;
    for (s = 0; s < nSnap; s++) {
      var upto = this.dayStart[Math.min(s * SNAP_DAYS, this.maxDay + 1)];
      for (; i < upto; i++) {
        if (this.accepts(i)) { acc[this.fips[i]]++; total++; }
      }
      snaps[s] = new Uint16Array(acc);
      totals[s] = total;
    }
    this._snaps = snaps;
    this._snapTotals = totals;
  };

  /* Cumulative county counts as of (and including) `targetDay`.
     Forward play advances incrementally; a seek restarts from the nearest snapshot. */
  Query.prototype.cumulativeTo = function (targetDay) {
    targetDay = clamp(targetDay | 0, -1, this.maxDay);
    if (!this._snaps) this._buildSnaps();

    var from;
    if (targetDay >= this._cursorDay && this._cursorDay >= 0) {
      from = this._cursorDay + 1;                       /* incremental: keep walking */
    } else {
      var s = Math.max(0, Math.floor((targetDay + 1) / SNAP_DAYS));
      if (s * SNAP_DAYS > targetDay + 1) s--;
      if (s < 0) s = 0;
      this._counts.set(this._snaps[s]);
      this._total = this._snapTotals[s];
      from = s * SNAP_DAYS;
    }
    var start = this.dayStart[clamp(from, 0, this.maxDay + 1)];
    var end = this.dayStart[clamp(targetDay + 1, 0, this.maxDay + 1)];
    for (var i = start; i < end; i++) {
      if (this.accepts(i)) { this._counts[this.fips[i]]++; this._total++; }
    }
    this._cursorDay = targetDay;
    return this._counts;
  };
  Query.prototype.total = function () { return this._total; };

  /* Per-county counts for an arbitrary window [d0,d1].
     d0 === 0 is the playback case, which delegates to the incremental accumulator;
     a brushed window walks the slice directly (48.6K events worst case, well under 1ms). */
  Query.prototype.countsInRange = function (d0, d1) {
    d0 = clamp(d0 | 0, 0, this.maxDay);
    d1 = clamp(d1 | 0, -1, this.maxDay);
    if (d0 === 0) return this.cumulativeTo(d1);
    if (!this._range || this._range.length !== this.nCounty) this._range = new Uint16Array(this.nCounty);
    var out = this._range;
    out.fill(0);
    var start = this.dayStart[clamp(d0, 0, this.maxDay + 1)];
    var end = this.dayStart[clamp(d1 + 1, 0, this.maxDay + 1)];
    var n = 0;
    for (var i = start; i < end; i++) {
      if (this.accepts(i)) { out[this.fips[i]]++; n++; }
    }
    this._rangeTotal = n;
    this._cursorDay = -1;          /* the incremental cursor no longer reflects _counts */
    return out;
  };
  Query.prototype.rangeTotal = function (d0) { return d0 === 0 ? this._total : this._rangeTotal; };

  /* Counties with at least one event in the window. */
  Query.prototype.countyHits = function (counts) {
    var n = 0;
    for (var i = 0; i < counts.length; i++) if (counts[i]) n++;
    return n;
  };

  /* Events occurring exactly on `day` and passing the filter (for bloom spawning). */
  Query.prototype.eventsOn = function (day, out) {
    out = out || [];
    out.length = 0;
    if (day < 0 || day > this.maxDay) return out;
    var start = this.dayStart[day], end = this.dayStart[day + 1];
    for (var i = start; i < end; i++) if (this.accepts(i)) out.push(i);
    return out;
  };

  /* Distinct declarations in [d0,d1] passing the filter — for counters/feed. */
  Query.prototype.declsIn = function (d0, d1) {
    var seen = Object.create(null), list = [];
    var start = this.dayStart[clamp(d0, 0, this.maxDay + 1)];
    var end = this.dayStart[clamp(d1 + 1, 0, this.maxDay + 1)];
    for (var i = start; i < end; i++) {
      if (!this.accepts(i)) continue;
      var k = this.decl[i];
      if (!seen[k]) { seen[k] = 1; list.push(k); }
    }
    return list;
  };

  /* Hazard histogram over [d0,d1] (county-events, filter-aware). */
  Query.prototype.hazardCounts = function (d0, d1) {
    var out = new Int32Array(this.hazards.length);
    var start = this.dayStart[clamp(d0, 0, this.maxDay + 1)];
    var end = this.dayStart[clamp(d1 + 1, 0, this.maxDay + 1)];
    for (var i = start; i < end; i++) if (this.accepts(i)) out[this.haz[i]]++;
    return out;
  };

  /* Per-day event counts across the whole span — drives the timeline sparkline. */
  Query.prototype.dailySeries = function () {
    var out = new Int32Array(this.maxDay + 1);
    for (var i = 0; i < this.n; i++) if (this.accepts(i)) out[this.day[i]]++;
    return out;
  };

  /* ══ money ═════════════════════════════════════════════════════════════
     FEMA publishes obligations as state x disaster (dated) or county totals (undated).
     There is no county x date, so dollars animate at STATE level and county dollars are
     all-time only. Amounts are stored in $ thousands. */

  Query.prototype.loadMoney = function (m) {
    this.money = m || null;
    if (!m) return this;
    /* county index -> state abbreviation, parsed from the "Name, ST" labels */
    var st = new Array(this.nCounty);
    for (var i = 0; i < this.nCounty; i++) {
      var lab = this.labels[i] || '', c = lab.lastIndexOf(',');
      st[i] = c >= 0 ? lab.slice(c + 1).trim() : '';
    }
    this.stateOf = st;
    /* county all-time dollars ($k), aligned to the county index */
    var cm = new Float64Array(this.nCounty);
    for (var f in m.counties) {
      var idx = this.fipsList.indexOf(f);
      if (idx >= 0) cm[idx] = m.counties[f][0];
    }
    this.countyMoney = cm;
    this.countyMoneyMeta = m.counties;
    return this;
  };

  /* Dollars ($k) by state for declarations in [d0,d1]. Honors the geo scope only in the
     sense that the caller decides what to show — money rows are state-grained. */
  Query.prototype.moneyStateInRange = function (d0, d1) {
    var out = {}, rows = this.money && this.money.dated;
    if (!rows) return out;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r[0] < d0 || r[0] > d1) continue;
      out[r[1]] = (out[r[1]] || 0) + r[3];
    }
    return out;
  };

  /* Spread state dollars across that state's counties for rendering (each county in a
     state carries the state's value — an explicit state-level choropleth, not an estimate). */
  Query.prototype.stateMoneyToCounties = function (byState, out) {
    out = out || new Float64Array(this.nCounty);
    for (var i = 0; i < this.nCounty; i++) out[i] = byState[this.stateOf[i]] || 0;
    return out;
  };

  Query.prototype.topMoneyDisasters = function (d0, d1, n) {
    var rows = this.money && this.money.dated;
    if (!rows) return [];
    var hits = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r[0] >= d0 && r[0] <= d1) hits.push(r);
    }
    hits.sort(function (a, b) { return b[3] - a[3]; });
    return hits.slice(0, n || 10);
  };

  /* ══ date helpers ══════════════════════════════════════════════════════ */
  var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function makeDates(epochIso) {
    var p = epochIso.split('-');
    var base = Date.UTC(+p[0], +p[1] - 1, +p[2]);
    return {
      toDate: function (day) { return new Date(base + day * 86400000); },
      label: function (day) {
        var d = new Date(base + day * 86400000);
        return MON[d.getUTCMonth()] + ' ' + d.getUTCDate() + ', ' + d.getUTCFullYear();
      },
      monthLabel: function (day) {
        var d = new Date(base + day * 86400000);
        return MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
      },
      year: function (day) { return new Date(base + day * 86400000).getUTCFullYear(); },
      dayOfYear: function (year) {                        /* first day-index of a calendar year */
        return Math.round((Date.UTC(year, 0, 1) - base) / 86400000);
      },
      dayOf: function (y, m, d) {                         /* calendar date -> day index */
        return Math.round((Date.UTC(y, m - 1, d) - base) / 86400000);
      }
    };
  }

  root.DD = {
    Store: Store, Query: Query, Ticker: Ticker, Seq: Seq,
    tween: tween, easeOut: easeOut, easeOutExpo: easeOutExpo, easeOutCubic: easeOutCubic,
    lerp: lerp, clamp: clamp, makeDates: makeDates,
    reduceMotion: reduceMotion, SNAP_DAYS: SNAP_DAYS
  };
})(window);
