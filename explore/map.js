/* Disaster Data — Explorer county map.

   Layered canvases, because redrawing 3,142 polygons every frame is not affordable:
     accumCanvas (offscreen) — the choropleth. Only counties whose count CHANGED get
                               repainted as the day cursor advances; a seek repaints all.
     view (visible)          — blit the offscreen, then draw bloom pulses on top.
     pick (offscreen)        — color-keyed county index for O(1) hover hit-testing,
                               redrawn only on resize.
   Geometry is the vendored us-atlas Albers topology: already projected, so there is no
   runtime projection cost and no CDN dependency. */
(function (root) {
  'use strict';

  var DD = root.DD;

  /* site heat ramp (index.html) + a neutral for "nothing yet" */
  var EMPTY = '#e9e5da';
  var RAMP = ['#f2d9a0', '#ecc278', '#e3a652', '#d8853a', '#c96a2e', '#b35024', '#97391b', '#7a2c14'];
  var BREAKS = [1, 2, 3, 5, 8, 13, 20, 35];
  function rampColor(v) {
    if (!v) return EMPTY;
    for (var i = BREAKS.length - 1; i >= 0; i--) if (v >= BREAKS[i]) return RAMP[i];
    return RAMP[0];
  }

  /* Dollars get their own teal ramp with caller-supplied breaks — money and counts must
     never be mistaken for one another. */
  var MRAMP = ['#d7e9ea', '#aed4d6', '#82bcc0', '#57a4a9', '#2e8b92', '#12727a', '#005c63', '#00434a'];
  var moneyBreaks = null;
  function moneyColor(v) {
    if (!v || !moneyBreaks) return EMPTY;
    for (var i = moneyBreaks.length - 1; i >= 0; i--) if (v >= moneyBreaks[i]) return MRAMP[i];
    return EMPTY;
  }
  /* quantile-ish breaks over the non-zero values currently in play */
  function setMoneyBreaks(values) {
    var v = [], i;
    for (i = 0; i < values.length; i++) if (values[i] > 0) v.push(values[i]);
    if (!v.length) { moneyBreaks = null; return null; }
    v.sort(function (a, b) { return a - b; });
    var qs = [0.10, 0.25, 0.42, 0.58, 0.72, 0.84, 0.93, 0.98], b = [];
    for (i = 0; i < qs.length; i++) b.push(v[Math.min(v.length - 1, Math.floor(v.length * qs[i]))]);
    for (i = 1; i < b.length; i++) if (b[i] <= b[i - 1]) b[i] = b[i - 1] + 1;
    moneyBreaks = b;
    return b;
  }

  /* hazard → hue, reusing the site's palette vocabulary */
  var HAZ_COLOR = {
    'Hurricane': '#0a6b73', 'Tropical Storm': '#0a6b73', 'Typhoon': '#0a6b73', 'Coastal Storm': '#0a6b73',
    'Tropical Depression': '#0a6b73',
    'Fire': '#c85c2e',
    'Flood': '#3f7fd6', 'Dam/Levee Break': '#3f7fd6', 'Mud/Landslide': '#7a5a3a',
    'Severe Storm': '#9e3a1e', 'Tornado': '#9e3a1e', 'Straight-Line Winds': '#9e3a1e',
    'Snowstorm': '#5b8fa8', 'Severe Ice Storm': '#5b8fa8', 'Winter Storm': '#5b8fa8', 'Freezing': '#5b8fa8',
    'Biological': '#0f8a6b', 'Earthquake': '#7a4a1e', 'Volcanic Eruption': '#7a2c14',
    'Drought': '#c9a227', 'Tsunami': '#3f7fd6', 'Chemical': '#8a5cb8', 'Toxic Substances': '#8a5cb8',
    'Terrorist': '#5b5346', 'Other': '#938a78', 'Unknown': '#938a78'
  };
  function hazColor(name) { return HAZ_COLOR[name] || '#938a78'; }

  var MAX_BLOOMS = 220;         /* COVID lands 3,232 county-events in one day — cap the particles */
  var BLOOM_MS = 1500;

  function ExploreMap(opts) {
    this.host = opts.host;
    this.query = opts.query;
    this.onHover = opts.onHover || function () {};
    this.onPick = opts.onPick || function () {};

    this.counties = [];          /* {fipsIdx, path:Path2D, cx, cy} */
    this.blooms = [];
    this.counts = null;
    this.prevCounts = null;
    this.dirty = [];
    this.focusFips = -1;
    this.hoverFips = -1;
    this.ready = false;

    this.view = document.createElement('canvas');
    this.view.className = 'xmap-canvas';
    this.host.appendChild(this.view);
    this.ctx = this.view.getContext('2d');

    this.accum = document.createElement('canvas');
    this.accumCtx = this.accum.getContext('2d');
    this.pick = document.createElement('canvas');
    this.pickCtx = this.pick.getContext('2d', { willReadFrequently: true });

    this._bind();
  }

  /* ── geometry ─────────────────────────────────────────────────────────── */

  /* Decode the baked geometry (explore-geo.js): counties pre-projected into a fixed
     975x610 Albers frame with territory insets, quantized to 1/q px and delta-encoded.
     No TopoJSON, no projection library, no CDN. */
  ExploreMap.prototype.load = function (geo) {
    var idx = {}, i;
    for (i = 0; i < this.query.fipsList.length; i++) idx[this.query.fipsList[i]] = i;

    this.frame = { w: geo.w, h: geo.h };
    var q = geo.q;

    /* rebuild absolute coordinates from the delta stream (units of 1/q px) */
    var d = geo.d, nd = d.length, abs = new Int32Array(nd), acc = 0;
    for (i = 0; i < nd; i++) { acc += d[i]; abs[i] = acc; }

    var ids = [], p = 0;
    for (i = 0; i < geo.idD.length; i++) { p += geo.idD[i]; ids.push(String(p).length < 5 ? ('00000' + p).slice(-5) : String(p)); }

    var out = [], ri = 0, ci = 0;
    for (i = 0; i < ids.length; i++) {
      var nr = geo.rc[i], rings = [];
      for (var r = 0; r < nr; r++) {
        var len = geo.rl[ri + r];
        rings.push(abs.subarray(ci, ci + len * 2));
        ci += len * 2;
      }
      ri += nr;
      var fi = idx[ids[i]];
      out.push({ fipsIdx: fi === undefined ? -1 : fi, rings: rings, path: null, cx: 0, cy: 0, id: ids[i] });
    }
    this.counties = out;
    this.q = q;

    /* state hairlines */
    var md = geo.md || [], mabs = new Int32Array(md.length), a2 = 0;
    for (i = 0; i < md.length; i++) { a2 += md[i]; mabs[i] = a2; }
    var lines = [], off = 0;
    for (i = 0; i < (geo.ml || []).length; i++) {
      var l = geo.ml[i];
      lines.push(mabs.subarray(off, off + l * 2));
      off += l * 2;
    }
    this.meshLines = lines;

    this.ready = true;
    this.resize();
    return this;
  };

  /* Build Path2D objects in device pixels for the current size. Geometry arrives in a
     fixed 975x610 frame at 1/q px, so this is a single uniform scale — no reprojection. */
  ExploreMap.prototype._buildPaths = function () {
    var fw = this.frame.w, fh = this.frame.h, q = this.q;
    var s = Math.min(this.w / fw, this.h / fh) / q;
    var ox = (this.w - fw * s * q) / 2, oy = (this.h - fh * s * q) / 2;
    this.scale = s; this.ox = ox; this.oy = oy;

    for (var i = 0; i < this.counties.length; i++) {
      var c = this.counties[i], p = new Path2D();
      var sx = 0, sy = 0, sn = 0;
      for (var r = 0; r < c.rings.length; r++) {
        var ring = c.rings[r], n = ring.length;
        for (var k = 0; k < n; k += 2) {
          var x = ring[k] * s + ox, y = ring[k + 1] * s + oy;
          if (k === 0) p.moveTo(x, y); else p.lineTo(x, y);
          if (r === 0) { sx += x; sy += y; sn++; }
        }
        p.closePath();
      }
      c.path = p;
      c.cx = sn ? sx / sn : 0;
      c.cy = sn ? sy / sn : 0;
    }

    var mp = new Path2D(), ls = this.meshLines || [];
    for (var m = 0; m < ls.length; m++) {
      var line = ls[m];
      for (var t = 0; t < line.length; t += 2) {
        var X = line[t] * s + ox, Y = line[t + 1] * s + oy;
        if (t === 0) mp.moveTo(X, Y); else mp.lineTo(X, Y);
      }
    }
    this.meshPath = ls.length ? mp : null;
  };

  /* ── sizing ───────────────────────────────────────────────────────────── */

  ExploreMap.prototype.resize = function () {
    if (!this.ready) return;
    var rect = this.host.getBoundingClientRect();
    var cssW = Math.max(320, rect.width | 0), cssH = Math.max(240, rect.height | 0);
    var dpr = Math.min(root.devicePixelRatio || 1, 2);   /* cap DPR — 3x on phones is wasteful */
    this.cssW = cssW; this.cssH = cssH; this.dpr = dpr;
    this.w = Math.round(cssW * dpr); this.h = Math.round(cssH * dpr);

    [this.view, this.accum, this.pick].forEach(function (cv) {
      cv.width = this.w; cv.height = this.h;
    }, this);
    this.view.style.width = cssW + 'px';
    this.view.style.height = cssH + 'px';

    this._buildPaths();
    this._pickBits = null;              /* rebuilt lazily on the next hover */
    this._fipsToCounty = null;
    this.repaintAll();
    this.needsRender = true;
  };

  /* ── picking (color-keyed offscreen) ──────────────────────────────────── */

  /* Painted lazily on first hover (saves ~95ms of boot), then read back ONCE into a
     Uint32Array — a per-mousemove getImageData costs ~20ms, an array index costs nothing. */
  ExploreMap.prototype._paintPick = function () {
    var c = this.pickCtx;
    c.clearRect(0, 0, this.w, this.h);
    for (var i = 0; i < this.counties.length; i++) {
      var n = i + 1;                                   /* 0 = background */
      c.fillStyle = 'rgb(' + (n & 255) + ',' + ((n >> 8) & 255) + ',' + ((n >> 16) & 255) + ')';
      c.fill(this.counties[i].path);
    }
    this._pickBits = new Uint32Array(c.getImageData(0, 0, this.w, this.h).data.buffer);
  };

  ExploreMap.prototype.countyAt = function (cssX, cssY) {
    if (!this.ready) return -1;
    if (!this._pickBits) this._paintPick();
    var x = Math.round(cssX * this.dpr), y = Math.round(cssY * this.dpr);
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return -1;
    var v = this._pickBits[y * this.w + x];            /* 0xAABBGGRR on little-endian */
    var n = v & 0xFFFFFF;
    return n ? n - 1 : -1;
  };

  /* ── choropleth ───────────────────────────────────────────────────────── */

  /* Full repaint — used on resize, seek, and filter change. */
  ExploreMap.prototype.repaintAll = function () {
    if (!this.ready) return;
    var c = this.accumCtx;
    var color = this.measure === 'dollars' ? moneyColor : rampColor;
    c.clearRect(0, 0, this.w, this.h);
    var counts = this.counts;
    for (var i = 0; i < this.counties.length; i++) {
      var cc = this.counties[i];
      var v = (counts && cc.fipsIdx >= 0) ? counts[cc.fipsIdx] : 0;
      c.fillStyle = color(v);
      c.fill(cc.path);
    }
    if (this.meshPath) {
      c.strokeStyle = 'rgba(138,124,94,.55)';
      c.lineWidth = Math.max(0.5, 0.6 * this.dpr);
      c.stroke(this.meshPath);
    }
    if (this.prevCounts && counts) this.prevCounts.set(counts);
    this.needsRender = true;
  };

  /* Incremental repaint — only counties whose value changed since last frame. */
  ExploreMap.prototype.applyCounts = function (counts, forceAll) {
    if (!this.ready) return;
    if (!this.prevCounts || this.prevCounts.length !== counts.length ||
        this.prevCounts.constructor !== counts.constructor) {
      this.prevCounts = new counts.constructor(counts.length);
      this.counts = counts;
      this.repaintAll();
      return;
    }
    this.counts = counts;
    if (forceAll || this.measure === 'dollars') { this.repaintAll(); return; }

    var c = this.accumCtx, prev = this.prevCounts, painted = 0;
    for (var i = 0; i < this.counties.length; i++) {
      var cc = this.counties[i];
      if (cc.fipsIdx < 0) continue;
      var v = counts[cc.fipsIdx];
      if (v === prev[cc.fipsIdx]) continue;
      c.fillStyle = rampColor(v);
      c.fill(cc.path);
      painted++;
    }
    if (painted) {
      /* county fills paint over the state hairlines — restore them */
      if (this.meshPath) {
        c.strokeStyle = 'rgba(138,124,94,.55)';
        c.lineWidth = Math.max(0.5, 0.6 * this.dpr);
        c.stroke(this.meshPath);
      }
      prev.set(counts);
      this.needsRender = true;
    }
    return painted;
  };

  /* ── blooms ───────────────────────────────────────────────────────────── */

  ExploreMap.prototype.spawn = function (eventIdxs) {
    if (DD.reduceMotion) return;
    var q = this.query, n = eventIdxs.length;
    var stride = n > MAX_BLOOMS ? Math.ceil(n / MAX_BLOOMS) : 1;
    var byFips = this._fipsToCounty || (this._fipsToCounty = this._buildFipsMap());
    for (var i = 0; i < n; i += stride) {
      var ei = eventIdxs[i];
      var cc = byFips[q.fips[ei]];
      if (!cc) continue;
      this.blooms.push({
        x: cc.cx, y: cc.cy, t: 0,
        color: hazColor(q.hazards[q.haz[ei]])
      });
    }
    if (this.blooms.length > MAX_BLOOMS * 2) this.blooms.splice(0, this.blooms.length - MAX_BLOOMS * 2);
    this.needsRender = true;
  };

  ExploreMap.prototype._buildFipsMap = function () {
    var m = {};
    for (var i = 0; i < this.counties.length; i++) {
      var c = this.counties[i];
      if (c.fipsIdx >= 0) m[c.fipsIdx] = c;
    }
    return m;
  };

  /* ── compose ──────────────────────────────────────────────────────────── */

  /* Compose. Skips entirely when idle (paused, no blooms, nothing moved) — a full-canvas
     clear + drawImage is the single most expensive thing here, so not doing it matters. */
  ExploreMap.prototype.render = function (dt) {
    if (!this.ready) return false;
    if (!this.needsRender && !this.blooms.length) return false;
    this.needsRender = false;
    var c = this.ctx;
    c.clearRect(0, 0, this.w, this.h);
    c.drawImage(this.accum, 0, 0);

    /* blooms */
    var b = this.blooms, alive = 0, dpr = this.dpr;
    for (var i = 0; i < b.length; i++) {
      var p = b[i];
      p.t += dt;
      var k = p.t / BLOOM_MS;
      if (k >= 1) continue;
      b[alive++] = p;
      var ease = 1 - Math.pow(1 - k, 3);
      var r = (3 + ease * 22) * dpr;
      c.globalAlpha = (1 - k) * 0.85;
      c.strokeStyle = p.color;
      c.lineWidth = Math.max(1, (2.2 - k * 1.4) * dpr);
      c.beginPath();
      c.arc(p.x, p.y, r, 0, Math.PI * 2);
      c.stroke();
      if (k < 0.45) {
        c.globalAlpha = (0.45 - k) * 1.1;
        c.fillStyle = p.color;
        c.beginPath();
        c.arc(p.x, p.y, r * 0.55, 0, Math.PI * 2);
        c.fill();
      }
    }
    b.length = alive;
    c.globalAlpha = 1;

    /* hover / focus outline */
    if (this.hoverFips >= 0 && this.counties[this.hoverFips]) {
      c.strokeStyle = '#1d1813';
      c.lineWidth = Math.max(1, 1.4 * dpr);
      c.stroke(this.counties[this.hoverFips].path);
    }
  };

  ExploreMap.prototype.hasBlooms = function () { return this.blooms.length > 0; };
  ExploreMap.prototype.clearBlooms = function () { this.blooms.length = 0; this.needsRender = true; };

  /* ── interaction ──────────────────────────────────────────────────────── */

  ExploreMap.prototype._bind = function () {
    var self = this;
    var moveTimer = 0;
    this.view.addEventListener('mousemove', function (e) {
      if (moveTimer) return;                     /* throttle picking to ~1 per frame */
      moveTimer = requestAnimationFrame(function () {
        moveTimer = 0;
        var r = self.view.getBoundingClientRect();
        var i = self.countyAt(e.clientX - r.left, e.clientY - r.top);
        if (i !== self.hoverFips) {
          self.hoverFips = i;
          self.needsRender = true;
          var c = i >= 0 ? self.counties[i] : null;
          self.onHover(c && c.fipsIdx >= 0 ? c.fipsIdx : -1, e.clientX, e.clientY);
        }
      });
    });
    this.view.addEventListener('mouseleave', function () {
      self.hoverFips = -1;
      self.needsRender = true;
      self.onHover(-1, 0, 0);
    });
    this.view.addEventListener('click', function (e) {
      var r = self.view.getBoundingClientRect();
      var i = self.countyAt(e.clientX - r.left, e.clientY - r.top);
      var c = i >= 0 ? self.counties[i] : null;
      self.onPick(c && c.fipsIdx >= 0 ? c.fipsIdx : -1);
    });
  };

  ExploreMap.prototype.setMeasure = function (m) {
    this.measure = m;
    this.prevCounts = null;
    this.needsRender = true;
  };

  root.DD.ExploreMap = ExploreMap;
  root.DD.hazColor = hazColor;
  root.DD.rampColor = rampColor;
  root.DD.moneyColor = moneyColor;
  root.DD.setMoneyBreaks = setMoneyBreaks;
  root.DD.MRAMP = MRAMP;
})(window);
