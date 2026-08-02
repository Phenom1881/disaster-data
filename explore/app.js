/* Disaster Data — Explorer app wiring.

   One state, four drivers: the clock (playback), the pointer (brush / map click /
   hazard toggles), the URL (a shared link), and the filters. Every view reads the same
   state and every view can write to it — that bidirectionality is the cockpit.

   Display model:
     winA..winB  the selected window (whole span unless the timeline is brushed)
     cursor      playback head inside that window
     shown data  = events in [winA, cursor]
   Playback animates cursor winA→winB. Brushing sets winA/winB and parks cursor at winB. */
(function (root) {
  'use strict';

  var DD = root.DD;
  var payload = root.EXPLORE_DATA;
  if (!payload) { console.error('Explorer: explore-data.js missing'); return; }

  var query = new DD.Query(payload);
  var dates = DD.makeDates(query.epoch);
  var ticker = new DD.Ticker();
  var Y0 = dates.year(0), Y1 = dates.year(query.maxDay);

  var store = new DD.Store({
    winA: 0, winB: query.maxDay, cursor: query.maxDay,
    brushed: false, playing: false, speed: 3,
    types: new Set(query.types),
    hazards: new Set(query.hazards),
    geo: null,            /* {state:'12'} | {fipsIdx:n} | null */
    selected: -1
  });

  var SPEEDS = [0, 120, 300, 700, 1400, 2600, 5200];   /* days per second */

  var el = {};
  ['mapwrap','hud-date','hud-sub','ctr-decl','ctr-county','ctr-events','play','play-icon','spd',
   'restart','copylink','timeline','tlaxis','hazlist','hazall','hazscope','typeseg','selbox',
   'feed','maptip','lg-sw','loading','chips'].forEach(function (id) {
    el[id.replace(/-(\w)/g, function (m, c) { return c.toUpperCase(); })] = document.getElementById(id);
  });

  function fmt(n) { return (n || 0).toLocaleString('en-US'); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&quot;'; }); }

  /* state FIPS → name, for the geo scope chip */
  var STNAME = {'01':'Alabama','02':'Alaska','04':'Arizona','05':'Arkansas','06':'California','08':'Colorado',
    '09':'Connecticut','10':'Delaware','11':'Washington DC','12':'Florida','13':'Georgia','15':'Hawaii',
    '16':'Idaho','17':'Illinois','18':'Indiana','19':'Iowa','20':'Kansas','21':'Kentucky','22':'Louisiana',
    '23':'Maine','24':'Maryland','25':'Massachusetts','26':'Michigan','27':'Minnesota','28':'Mississippi',
    '29':'Missouri','30':'Montana','31':'Nebraska','32':'Nevada','33':'New Hampshire','34':'New Jersey',
    '35':'New Mexico','36':'New York','37':'North Carolina','38':'North Dakota','39':'Ohio','40':'Oklahoma',
    '41':'Oregon','42':'Pennsylvania','44':'Rhode Island','45':'South Carolina','46':'South Dakota',
    '47':'Tennessee','48':'Texas','49':'Utah','50':'Vermont','51':'Virginia','53':'Washington',
    '54':'West Virginia','55':'Wisconsin','56':'Wyoming','60':'American Samoa','66':'Guam',
    '69':'N. Mariana Islands','72':'Puerto Rico','78':'U.S. Virgin Islands'};

  /* ── map ──────────────────────────────────────────────────────────────── */

  var xmap = new DD.ExploreMap({
    host: el.mapwrap,
    query: query,
    onHover: function (fipsIdx, x, y) {
      if (fipsIdx < 0) { el.maptip.style.opacity = '0'; return; }
      var c = lastCounts ? lastCounts[fipsIdx] : 0;
      el.maptip.innerHTML = '<b>' + esc(query.labels[fipsIdx]) + '</b><br>' +
        fmt(c) + ' declaration' + (c === 1 ? '' : 's') + ' in view';
      el.maptip.style.left = x + 'px';
      el.maptip.style.top = y + 'px';
      el.maptip.style.opacity = '1';
    },
    onPick: function (fipsIdx) {
      if (fipsIdx < 0) { setGeo(null); return; }
      /* click selects the county; click again on the same one scopes to its state */
      var s = store.state;
      if (s.selected === fipsIdx && s.geo && s.geo.fipsIdx === fipsIdx) {
        setGeo({ state: query.fipsList[fipsIdx].slice(0, 2) });
      } else {
        store.set({ selected: fipsIdx });
        setGeo({ fipsIdx: fipsIdx });
      }
    }
  });

  /* ── derived ──────────────────────────────────────────────────────────── */

  var lastCounts = null, dailySeries = null, seriesDirty = true;

  function applyQueryFilter() {
    var s = store.state;
    query.setFilter(s.types, s.hazards, query.geoMask(s.geo));
    seriesDirty = true;
  }

  /* Recompute everything that depends on [winA, cursor] + filters. */
  function refresh(forceRepaint) {
    var s = store.state;
    var counts = query.countsInRange(s.winA, s.cursor);
    lastCounts = counts;
    xmap.applyCounts(counts, forceRepaint || s.winA !== 0);
    el.ctrEvents.textContent = fmt(query.rangeTotal(s.winA));
    el.ctrCounty.textContent = fmt(query.countyHits(counts));
    el.ctrDecl.textContent = fmt(query.declsIn(s.winA, s.cursor).length);
    el.hudDate.textContent = dates.label(s.cursor);
    el.hudSub.textContent = s.playing ? 'Replaying…'
      : (s.brushed ? dates.monthLabel(s.winA) + ' – ' + dates.monthLabel(s.winB)
                   : (s.cursor >= query.maxDay ? 'Full record, ' + Y0 + '–' + Y1 : 'Paused'));
    renderHazCounts();
    renderFeed();
    renderSelection();
    renderChips();
  }

  /* ── hazards (live, scoped to window + geo) ───────────────────────────── */

  var hazOrder = null;
  function buildHazList() {
    if (!hazOrder) {
      var saveT = store.state.types, saveH = store.state.hazards, saveG = store.state.geo;
      query.setFilter(null, null, null);
      var totals = query.hazardCounts(0, query.maxDay);
      hazOrder = query.hazards.map(function (h, i) { return { name: h, i: i, all: totals[i] }; })
                              .sort(function (a, b) { return b.all - a.all; });
      query.setFilter(saveT, saveH, query.geoMask(saveG));
    }
    el.hazlist.innerHTML = hazOrder.map(function (h) {
      return '<button class="hz" data-h="' + esc(h.name) + '">' +
        '<i style="background:' + DD.hazColor(h.name) + '"></i>' +
        '<span class="nm">' + esc(h.name) + '</span>' +
        '<span class="ct" data-c="' + h.i + '">0</span></button>';
    }).join('');
    syncHazUI();
  }

  /* Counts must ignore the hazard filter itself (so you can see what turning one back on
     would add) but honor the window, type filter and geo scope. */
  function renderHazCounts() {
    var s = store.state;
    query.setFilter(s.types, null, query.geoMask(s.geo));
    var counts = query.hazardCounts(s.winA, s.cursor);
    query.setFilter(s.types, s.hazards, query.geoMask(s.geo));
    [].forEach.call(el.hazlist.querySelectorAll('.ct'), function (n) {
      n.textContent = fmt(counts[+n.dataset.c]);
    });
    var bits = [];
    if (s.brushed) bits.push(dates.monthLabel(s.winA) + '–' + dates.monthLabel(s.winB));
    if (s.geo) bits.push(geoLabel(s.geo));
    el.hazscope.textContent = bits.length ? 'in ' + bits.join(' · ') : 'across the full record';
  }
  function syncHazUI() {
    var on = store.state.hazards;
    [].forEach.call(el.hazlist.querySelectorAll('.hz'), function (b) {
      b.classList.toggle('off', !on.has(b.dataset.h));
    });
  }

  /* ── chips (active cross-filters) ─────────────────────────────────────── */

  function geoLabel(g) {
    if (!g) return '';
    if (g.fipsIdx != null) return query.labels[g.fipsIdx] || query.fipsList[g.fipsIdx];
    return STNAME[g.state] || ('State ' + g.state);
  }
  function renderChips() {
    var s = store.state, out = [];
    if (s.brushed) {
      out.push('<button class="chip win" data-act="clearwin">' +
        dates.monthLabel(s.winA) + ' – ' + dates.monthLabel(s.winB) +
        ' <span class="x" aria-hidden="true">×</span></button>');
    }
    if (s.geo) {
      out.push('<button class="chip" data-act="cleargeo">' + esc(geoLabel(s.geo)) +
        ' <span class="x" aria-hidden="true">×</span></button>');
    }
    var offH = query.hazards.length - s.hazards.size;
    if (offH > 0) {
      out.push('<button class="chip" data-act="clearhaz">' + s.hazards.size + ' of ' +
        query.hazards.length + ' hazards <span class="x" aria-hidden="true">×</span></button>');
    }
    if (s.types.size < query.types.length) {
      var list = query.types.filter(function (t) { return s.types.has(t); }).join(' + ');
      out.push('<button class="chip" data-act="cleartype">' + list +
        ' only <span class="x" aria-hidden="true">×</span></button>');
    }
    el.chips.innerHTML = out.join('');
  }
  el.chips.addEventListener('click', function (e) {
    var b = e.target.closest('.chip'); if (!b) return;
    var a = b.dataset.act, s = store.state;
    if (a === 'clearwin') { store.set({ winA: 0, winB: query.maxDay, cursor: query.maxDay, brushed: false }); }
    else if (a === 'cleargeo') { setGeo(null); return; }
    else if (a === 'clearhaz') { s.hazards = new Set(query.hazards); syncHazUI(); applyQueryFilter(); }
    else if (a === 'cleartype') {
      s.types = new Set(query.types);
      [].forEach.call(el.typeseg.querySelectorAll('button'), function (x) { x.classList.add('on'); });
      applyQueryFilter();
    }
    refresh(true); drawTimeline(); pushURL();
  });

  /* ── timeline: brush + scrub ──────────────────────────────────────────── */

  function drawTimeline() {
    var cv = el.timeline, dpr = Math.min(root.devicePixelRatio || 1, 2);
    var w = cv.clientWidth, h = 56;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    var c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);

    if (seriesDirty || !dailySeries) { dailySeries = query.dailySeries(); seriesDirty = false; }

    var s = store.state, n = query.maxDay + 1;
    var cols = new Float64Array(w), peak = 1, i;
    for (var d = 0; d < n; d++) cols[(d / n * w) | 0] += dailySeries[d];
    for (i = 0; i < w; i++) if (cols[i] > peak) peak = cols[i];

    var xA = s.winA / n * w, xB = s.winB / n * w, xC = s.cursor / n * w;

    if (s.brushed) {                       /* dim outside the brushed window */
      c.fillStyle = 'rgba(246,241,231,.75)';
      c.fillRect(0, 0, xA, h - 11);
      c.fillRect(xB, 0, w - xB, h - 11);
      c.fillStyle = 'rgba(200,92,46,.07)';
      c.fillRect(xA, 0, xB - xA, h - 11);
    }
    for (var px = 0; px < w; px++) {
      var v = cols[px];
      if (!v) continue;
      var bh = Math.max(1, Math.pow(v / peak, 0.6) * (h - 14));
      var inWin = px >= xA && px <= xB;
      c.fillStyle = (inWin && px <= xC) ? '#c85c2e' : (inWin ? '#d8cebb' : '#e6dfd0');
      c.fillRect(px, h - 12 - bh, 1, bh);
    }
    c.fillStyle = '#e0d8c5'; c.fillRect(0, h - 12, w, 1);
    for (var y = Y0 + 1; y <= Y1; y++) {
      if (y % 5) continue;
      c.fillStyle = '#cfc6b0';
      c.fillRect(dates.dayOfYear(y) / n * w, h - 12, 1, 5);
    }
    if (s.brushed) {                       /* brush edges */
      c.fillStyle = '#c85c2e';
      c.fillRect(xA - 1, 0, 2, h - 10);
      c.fillRect(xB - 1, 0, 2, h - 10);
    }
    c.fillStyle = '#1d1813';
    c.fillRect(xC - 0.5, 0, 1.5, h - 8);
    c.beginPath(); c.arc(xC, h - 8, 3.5, 0, Math.PI * 2); c.fill();
  }

  function buildAxis() {
    var out = [];
    for (var y = Y0; y <= Y1; y += 5) out.push('<span>' + y + '</span>');
    el.tlaxis.innerHTML = out.join('');
  }

  function dayAt(e) {
    var r = el.timeline.getBoundingClientRect();
    var cx = (e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX) - r.left;
    return Math.round(DD.clamp(cx / r.width, 0, 1) * query.maxDay);
  }

  var drag = null;   /* {mode:'new'|'a'|'b'|'seek', origin} */
  var DRAG_PX = 5;

  function onDown(e) {
    var s = store.state, d = dayAt(e), r = el.timeline.getBoundingClientRect();
    var perPx = query.maxDay / r.width, near = DRAG_PX * perPx;
    setPlaying(false);
    if (s.brushed && Math.abs(d - s.winA) < near) drag = { mode: 'a' };
    else if (s.brushed && Math.abs(d - s.winB) < near) drag = { mode: 'b' };
    else drag = { mode: 'new', origin: d, moved: false };
    e.preventDefault();
  }
  function onMove(e) {
    if (!drag) return;
    var d = dayAt(e), s = store.state;
    if (drag.mode === 'new') {
      if (!drag.moved && Math.abs(d - drag.origin) < 2) return;   /* still a click */
      drag.moved = true;
      var a = Math.min(drag.origin, d), b = Math.max(drag.origin, d);
      store.set({ winA: a, winB: b, cursor: b, brushed: true });
    } else if (drag.mode === 'a') {
      store.set({ winA: Math.min(d, s.winB - 1), cursor: s.winB, brushed: true });
    } else {
      store.set({ winB: Math.max(d, s.winA + 1), cursor: Math.max(d, s.winA + 1), brushed: true });
    }
    applyQueryFilter();
    refresh(true); drawTimeline();
  }
  function onUp(e) {
    if (!drag) return;
    if (drag.mode === 'new' && !drag.moved) {          /* click = seek within the window */
      var s = store.state;
      store.set({ cursor: DD.clamp(dayAt(e), s.winA, s.winB) });
      xmap.clearBlooms();
      refresh(true); drawTimeline();
    }
    drag = null;
    pushURL();
  }
  el.timeline.addEventListener('mousedown', onDown);
  root.addEventListener('mousemove', onMove);
  root.addEventListener('mouseup', onUp);
  el.timeline.addEventListener('touchstart', onDown, { passive: false });
  root.addEventListener('touchmove', onMove, { passive: true });
  root.addEventListener('touchend', onUp);
  el.timeline.addEventListener('dblclick', function () {
    store.set({ winA: 0, winB: query.maxDay, cursor: query.maxDay, brushed: false });
    applyQueryFilter(); refresh(true); drawTimeline(); pushURL();
  });

  /* ── feed / selection ─────────────────────────────────────────────────── */

  function renderFeed() {
    var s = store.state;
    var from = s.brushed || s.geo ? s.winA : Math.max(s.winA, s.cursor - 45);
    var list = query.declsIn(from, s.cursor);
    if (!list.length) { el.feed.innerHTML = '<div class="muted">Nothing matches these filters.</div>'; return; }
    var html = '';
    for (var i = list.length - 1, n = 0; i >= 0 && n < 14; i--, n++) {
      var d = query.decls[list[i]];
      html += '<div class="fitem"><div class="ft">' + esc(d[1] || d[0]) + '</div>' +
        '<div class="fm">' + esc(d[0]) + ' &middot; ' + esc(d[2]) + '</div></div>';
    }
    el.feed.innerHTML = html;
  }

  function renderSelection() {
    var i = store.state.selected;
    if (i < 0) { el.selbox.innerHTML = '<div class="muted">Click a county to scope everything to it. Click again for its whole state.</div>'; return; }
    var c = lastCounts ? lastCounts[i] : 0;
    el.selbox.innerHTML =
      '<div class="nm">' + esc(query.labels[i]) + '</div>' +
      '<div class="mt">FIPS ' + esc(query.fipsList[i]) + '</div>' +
      '<div class="big">' + fmt(c) + '</div>' +
      '<div class="bl">declarations in view</div>';
  }

  /* ── geo scope ────────────────────────────────────────────────────────── */

  function setGeo(g) {
    store.set({ geo: g });
    if (!g) store.set({ selected: -1 });
    applyQueryFilter();
    refresh(true); drawTimeline(); pushURL();
  }

  /* ── playback ─────────────────────────────────────────────────────────── */

  var acc = 0;
  function tick(dt) {
    var s = store.state;
    if (s.playing) {
      acc += (SPEEDS[s.speed] || 300) * (dt / 1000);
      if (acc >= 1) {
        var step = Math.floor(acc); acc -= step;
        var next = s.cursor + step, done = false;
        if (next >= s.winB) { next = s.winB; done = true; }
        var evs = [];
        for (var d = s.cursor + 1; d <= next && evs.length < 900; d++) {
          var day = query.eventsOn(d, []);
          for (var k = 0; k < day.length; k++) evs.push(day[k]);
        }
        store.set({ cursor: next });
        if (evs.length) xmap.spawn(evs);
        refresh(false);
        drawTimeline();
        if (done) setPlaying(false);
      }
    }
    xmap.render(dt);
  }

  function setPlaying(on) {
    var s = store.state;
    if (on && s.cursor >= s.winB) { store.set({ cursor: s.winA }); xmap.clearBlooms(); refresh(true); }
    store.set({ playing: on });
    el.playIcon.innerHTML = on
      ? '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'
      : '<path d="M7 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 7 5.5z"/>';
    el.play.setAttribute('aria-label', on ? 'Pause the replay' : 'Play the replay');
    if (!on) refresh(false);
  }

  el.play.addEventListener('click', function () { setPlaying(!store.state.playing); });
  el.restart.addEventListener('click', function () {
    setPlaying(false); xmap.clearBlooms();
    store.set({ cursor: store.state.winA });
    refresh(true); drawTimeline();
  });
  el.spd.addEventListener('input', function () { store.set({ speed: +this.value }); });

  el.typeseg.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var t = b.dataset.t, set = store.state.types;
    if (set.has(t)) { if (set.size === 1) return; set.delete(t); } else set.add(t);
    b.classList.toggle('on', set.has(t));
    applyQueryFilter(); refresh(true); drawTimeline(); pushURL();
  });

  el.hazlist.addEventListener('click', function (e) {
    var b = e.target.closest('.hz'); if (!b) return;
    var h = b.dataset.h, set = store.state.hazards;
    if (set.has(h)) { if (set.size === 1) return; set.delete(h); } else set.add(h);
    syncHazUI(); applyQueryFilter(); refresh(true); drawTimeline(); pushURL();
  });
  el.hazall.addEventListener('click', function () {
    store.state.hazards = new Set(query.hazards);
    syncHazUI(); applyQueryFilter(); refresh(true); drawTimeline(); pushURL();
  });

  document.addEventListener('keydown', function (e) {
    if (e.target && /input|select|textarea/i.test(e.target.tagName)) return;
    var s = store.state;
    if (e.code === 'Space') { e.preventDefault(); setPlaying(!s.playing); }
    else if (e.key === 'ArrowRight') { store.set({ cursor: DD.clamp(s.cursor + (e.shiftKey ? 30 : 1), s.winA, s.winB) }); refresh(true); drawTimeline(); }
    else if (e.key === 'ArrowLeft') { store.set({ cursor: DD.clamp(s.cursor - (e.shiftKey ? 30 : 1), s.winA, s.winB) }); refresh(true); drawTimeline(); }
    else if (e.key === 'Home') { store.set({ cursor: s.winA }); refresh(true); drawTimeline(); }
    else if (e.key === 'End') { store.set({ cursor: s.winB }); refresh(true); drawTimeline(); }
    else if (e.key === 'Escape') { setGeo(null); }
  });

  /* ── URL state ────────────────────────────────────────────────────────── */

  function pushURL() {
    var s = store.state, p = new URLSearchParams();
    if (s.brushed) p.set('w', s.winA + '-' + s.winB);
    if (s.geo) p.set('g', s.geo.fipsIdx != null ? query.fipsList[s.geo.fipsIdx] : s.geo.state);
    if (s.types.size < query.types.length) p.set('t', query.types.filter(function (t) { return s.types.has(t); }).join('.'));
    if (s.hazards.size < query.hazards.length) {
      p.set('h', query.hazards.map(function (h, i) { return s.hazards.has(h) ? i : -1; })
                              .filter(function (i) { return i >= 0; }).join('.'));
    }
    var q = p.toString();
    try { history.replaceState(null, '', q ? '?' + q : location.pathname); } catch (err) {}
  }

  function applyURL() {
    var p;
    try { p = new URLSearchParams(location.search); } catch (e) { return; }
    var s = store.state, w = p.get('w');
    if (w && /^\d+-\d+$/.test(w)) {
      var ab = w.split('-'), a = DD.clamp(+ab[0], 0, query.maxDay), b = DD.clamp(+ab[1], 0, query.maxDay);
      if (a < b) { s.winA = a; s.winB = b; s.cursor = b; s.brushed = true; }
    }
    var g = p.get('g');
    if (g) {
      if (g.length === 5) { var i = query.fipsList.indexOf(g); if (i >= 0) { s.geo = { fipsIdx: i }; s.selected = i; } }
      else if (g.length === 2) s.geo = { state: g };
    }
    var t = p.get('t');
    if (t) {
      var want = t.split('.').filter(function (x) { return query.types.indexOf(x) >= 0; });
      if (want.length) {
        s.types = new Set(want);
        [].forEach.call(el.typeseg.querySelectorAll('button'), function (b) {
          b.classList.toggle('on', s.types.has(b.dataset.t));
        });
      }
    }
    var h = p.get('h');
    if (h) {
      var idxs = h.split('.').map(Number).filter(function (i) { return i >= 0 && i < query.hazards.length; });
      if (idxs.length) s.hazards = new Set(idxs.map(function (i) { return query.hazards[i]; }));
    }
  }

  el.copylink.addEventListener('click', function () {
    pushURL();
    var url = location.href, btn = this, prev = btn.textContent;
    var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = prev; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, function () { root.prompt('Copy link:', url); });
    else root.prompt('Copy link:', url);
  });

  var rt = 0;
  root.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () { xmap.resize(); drawTimeline(); }, 120);
  });

  /* ── boot ─────────────────────────────────────────────────────────────── */

  el.lgSw.innerHTML = ['#f2d9a0','#ecc278','#e3a652','#d8853a','#c96a2e','#b35024','#97391b','#7a2c14']
    .map(function (c) { return '<i style="background:' + c + '"></i>'; }).join('');

  function boot(geo) {
    xmap.load(geo);
    applyURL();
    buildHazList();
    applyQueryFilter();
    syncHazUI();
    buildAxis();
    refresh(true);
    drawTimeline();
    el.loading.style.display = 'none';
    ticker.add(tick);
    root.__DD_READY = true;
  }

  if (root.EXPLORE_GEO) boot(root.EXPLORE_GEO);
  else {
    console.error('Explorer: explore-geo.js missing');
    el.loading.innerHTML = '<div class="msg">Could not load the county map.</div>' +
      '<div class="muted" style="font-size:12px">Reload, or use the <a href="map.html" style="color:#004c53">classic map</a>.</div>';
  }

  root.__DD = { store: store, query: query, map: xmap, dates: dates, refresh: refresh,
                setPlaying: setPlaying, setGeo: setGeo, drawTimeline: drawTimeline,
                applyQueryFilter: applyQueryFilter, pushURL: pushURL };
})(window);
