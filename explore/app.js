/* Disaster Data — Explorer app wiring.
   Drives the store from three sources (clock during playback, user during scrub/filter)
   and fans state out to the map, HUD, counters, timeline, hazard list and feed. */
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
    day: query.maxDay,          /* start showing the full 25 years */
    playing: false,
    speed: 3,
    types: new Set(query.types),
    hazards: new Set(query.hazards),
    selected: -1
  });

  /* days advanced per second, by speed notch */
  var SPEEDS = [0, 120, 300, 700, 1400, 2600, 5200];

  var el = {
    wrap: document.getElementById('mapwrap'),
    date: document.getElementById('hud-date'),
    sub: document.getElementById('hud-sub'),
    decl: document.getElementById('ctr-decl'),
    county: document.getElementById('ctr-county'),
    events: document.getElementById('ctr-events'),
    play: document.getElementById('play'),
    playIcon: document.getElementById('play-icon'),
    spd: document.getElementById('spd'),
    restart: document.getElementById('restart'),
    tl: document.getElementById('timeline'),
    tlaxis: document.getElementById('tlaxis'),
    hazlist: document.getElementById('hazlist'),
    hazall: document.getElementById('hazall'),
    typeseg: document.getElementById('typeseg'),
    selbox: document.getElementById('selbox'),
    feed: document.getElementById('feed'),
    tip: document.getElementById('maptip'),
    legend: document.getElementById('lg-sw'),
    loading: document.getElementById('loading')
  };

  function fmt(n) { return (n || 0).toLocaleString('en-US'); }

  /* ── map ──────────────────────────────────────────────────────────────── */

  var xmap = new DD.ExploreMap({
    host: el.wrap,
    query: query,
    onHover: function (fipsIdx, x, y) {
      if (fipsIdx < 0) { el.tip.style.opacity = '0'; return; }
      var counts = query.cumulativeTo(store.state.day);
      el.tip.innerHTML = '<b>' + query.labels[fipsIdx] + '</b><br>' +
        fmt(counts[fipsIdx]) + ' declaration' + (counts[fipsIdx] === 1 ? '' : 's') + ' to date';
      el.tip.style.left = x + 'px';
      el.tip.style.top = y + 'px';
      el.tip.style.opacity = '1';
    },
    onPick: function (fipsIdx) {
      store.set({ selected: fipsIdx }, ['selected']);
    }
  });

  /* ── derived state ────────────────────────────────────────────────────── */

  var lastDay = -1, dailySeries = null, seriesDirty = true;

  function refreshCounts(force) {
    var s = store.state;
    var counts = query.cumulativeTo(s.day);
    xmap.applyCounts(counts, force);
    var hit = 0;
    for (var i = 0; i < counts.length; i++) if (counts[i]) hit++;
    el.events.textContent = fmt(query.total());
    el.county.textContent = fmt(hit);
    el.decl.textContent = fmt(query.declsIn(0, s.day).length);
    el.date.textContent = dates.label(s.day);
    el.sub.textContent = s.playing ? 'Replaying…' : (s.day >= query.maxDay ? 'Full record, ' + Y0 + '–' + Y1 : 'Paused');
  }

  /* ── hazards ──────────────────────────────────────────────────────────── */

  var hazTotals = null;
  function buildHazList() {
    var all = query.hazards.map(function (h, i) { return { name: h, i: i }; });
    if (!hazTotals) {
      hazTotals = new Int32Array(query.hazards.length);
      var saveT = store.state.types, saveH = store.state.hazards;
      query.setFilter(null, null);
      hazTotals = query.hazardCounts(0, query.maxDay);
      query.setFilter(saveT, saveH);
    }
    all.sort(function (a, b) { return hazTotals[b.i] - hazTotals[a.i]; });
    el.hazlist.innerHTML = all.map(function (h) {
      return '<button class="hz" data-h="' + h.name.replace(/"/g, '&quot;') + '">' +
        '<i style="background:' + DD.hazColor(h.name) + '"></i>' +
        '<span class="nm">' + h.name + '</span>' +
        '<span class="ct">' + fmt(hazTotals[h.i]) + '</span></button>';
    }).join('');
    syncHazUI();
  }
  function syncHazUI() {
    var on = store.state.hazards;
    [].forEach.call(el.hazlist.querySelectorAll('.hz'), function (b) {
      b.classList.toggle('off', !on.has(b.dataset.h));
    });
  }

  function applyFilter() {
    query.setFilter(store.state.types, store.state.hazards);
    seriesDirty = true;
    refreshCounts(true);
    drawTimeline();
    renderFeed();
  }

  /* ── timeline ─────────────────────────────────────────────────────────── */

  function drawTimeline() {
    var cv = el.tl, dpr = Math.min(root.devicePixelRatio || 1, 2);
    var w = cv.clientWidth, h = 56;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    var c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);

    if (seriesDirty || !dailySeries) { dailySeries = query.dailySeries(); seriesDirty = false; }

    /* bucket days into pixel columns */
    var n = query.maxDay + 1, peak = 1, cols = new Float64Array(w);
    for (var d = 0; d < n; d++) {
      var x = (d / n * w) | 0;
      cols[x] += dailySeries[d];
    }
    for (var i = 0; i < w; i++) if (cols[i] > peak) peak = cols[i];

    var cursorX = store.state.day / n * w;
    for (var px = 0; px < w; px++) {
      var v = cols[px];
      if (!v) continue;
      var bh = Math.max(1, Math.pow(v / peak, 0.6) * (h - 14));
      c.fillStyle = px <= cursorX ? '#c85c2e' : '#d8cebb';
      c.fillRect(px, h - 12 - bh, 1, bh);
    }
    /* year ticks */
    c.fillStyle = '#e0d8c5';
    c.fillRect(0, h - 12, w, 1);
    for (var y = Y0 + 1; y <= Y1; y++) {
      if (y % 5) continue;
      var tx = dates.dayOfYear(y) / n * w;
      c.fillStyle = '#cfc6b0';
      c.fillRect(tx, h - 12, 1, 5);
    }
    /* cursor */
    c.fillStyle = '#1d1813';
    c.fillRect(cursorX - 0.5, 0, 1.5, h - 8);
    c.beginPath();
    c.arc(cursorX, h - 8, 3.5, 0, Math.PI * 2);
    c.fill();
  }

  function buildAxis() {
    var out = [];
    for (var y = Y0; y <= Y1; y += 5) out.push('<span>' + y + '</span>');
    if (out.length < 2) out.push('<span>' + Y1 + '</span>');
    el.tlaxis.innerHTML = out.join('');
  }

  function dayFromEvent(e) {
    var r = el.tl.getBoundingClientRect();
    var cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    var frac = DD.clamp(cx / r.width, 0, 1);
    return Math.round(frac * query.maxDay);
  }

  var scrubbing = false;
  function beginScrub(e) {
    scrubbing = true;
    setPlaying(false);
    seek(dayFromEvent(e));
    e.preventDefault();
  }
  function moveScrub(e) { if (scrubbing) seek(dayFromEvent(e)); }
  function endScrub() { scrubbing = false; }
  el.tl.addEventListener('mousedown', beginScrub);
  root.addEventListener('mousemove', moveScrub);
  root.addEventListener('mouseup', endScrub);
  el.tl.addEventListener('touchstart', beginScrub, { passive: false });
  root.addEventListener('touchmove', moveScrub, { passive: true });
  root.addEventListener('touchend', endScrub);

  function seek(day) {
    day = DD.clamp(day, 0, query.maxDay);
    if (day === store.state.day) return;
    var jumped = Math.abs(day - store.state.day) > 3;
    store.set({ day: day }, ['day']);
    if (jumped) xmap.clearBlooms();
    refreshCounts(jumped);
    drawTimeline();
    renderFeed();
  }

  /* ── feed ─────────────────────────────────────────────────────────────── */

  function renderFeed() {
    var s = store.state;
    var from = Math.max(0, s.day - 45);
    var list = query.declsIn(from, s.day);
    if (!list.length) { el.feed.innerHTML = '<div class="muted">No declarations in this window.</div>'; return; }
    var html = '';
    for (var i = list.length - 1, shown = 0; i >= 0 && shown < 12; i--, shown++) {
      var d = query.decls[list[i]];
      html += '<div class="fitem"><div class="ft">' + (d[1] || d[0]) + '</div>' +
        '<div class="fm">' + d[0] + ' &middot; ' + d[2] + '</div></div>';
    }
    el.feed.innerHTML = html;
  }

  /* ── selection ────────────────────────────────────────────────────────── */

  function renderSelection() {
    var i = store.state.selected;
    if (i < 0) { el.selbox.innerHTML = '<div class="muted">Click any county on the map.</div>'; return; }
    var counts = query.cumulativeTo(store.state.day);
    el.selbox.innerHTML =
      '<div class="nm">' + query.labels[i] + '</div>' +
      '<div class="mt">FIPS ' + query.fipsList[i] + '</div>' +
      '<div class="big">' + fmt(counts[i]) + '</div>' +
      '<div class="bl">declarations to date</div>';
  }

  /* ── playback ─────────────────────────────────────────────────────────── */

  var acc = 0;
  function tick(dt) {
    var s = store.state;
    if (s.playing) {
      acc += (SPEEDS[s.speed] || 300) * (dt / 1000);
      if (acc >= 1) {
        var step = Math.floor(acc);
        acc -= step;
        var next = s.day + step;
        if (next >= query.maxDay) { next = query.maxDay; setPlaying(false); }
        /* spawn blooms for the days we just crossed */
        var evs = [];
        for (var d = s.day + 1; d <= next; d++) {
          var day = query.eventsOn(d, []);
          for (var k = 0; k < day.length; k++) evs.push(day[k]);
          if (evs.length > 900) break;
        }
        store.set({ day: next }, ['day']);
        if (evs.length) xmap.spawn(evs);
        refreshCounts(false);
        drawTimeline();
        renderFeed();
        if (store.state.selected >= 0) renderSelection();
      }
    }
    xmap.render(dt);
  }

  function setPlaying(on) {
    if (on && store.state.day >= query.maxDay) { seek(0); xmap.clearBlooms(); }
    store.set({ playing: on }, ['playing']);
    el.playIcon.innerHTML = on
      ? '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'
      : '<path d="M7 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 7 5.5z"/>';
    el.play.setAttribute('aria-label', on ? 'Pause the replay' : 'Play the 25-year replay');
    el.sub.textContent = on ? 'Replaying…' : (store.state.day >= query.maxDay ? 'Full record, ' + Y0 + '–' + Y1 : 'Paused');
  }

  el.play.addEventListener('click', function () { setPlaying(!store.state.playing); });
  el.restart.addEventListener('click', function () {
    setPlaying(false); xmap.clearBlooms(); seek(0);
  });
  el.spd.addEventListener('input', function () { store.set({ speed: +this.value }, ['speed']); });

  el.typeseg.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var t = b.dataset.t, set = store.state.types;
    if (set.has(t)) { if (set.size === 1) return; set.delete(t); } else set.add(t);
    b.classList.toggle('on', set.has(t));
    applyFilter();
  });

  el.hazlist.addEventListener('click', function (e) {
    var b = e.target.closest('.hz'); if (!b) return;
    var h = b.dataset.h, set = store.state.hazards;
    if (set.has(h)) { if (set.size === 1) return; set.delete(h); } else set.add(h);
    syncHazUI();
    applyFilter();
  });
  el.hazall.addEventListener('click', function () {
    store.state.hazards = new Set(query.hazards);
    syncHazUI(); applyFilter();
  });

  document.addEventListener('keydown', function (e) {
    if (e.target && /input|select|textarea/i.test(e.target.tagName)) return;
    if (e.code === 'Space') { e.preventDefault(); setPlaying(!store.state.playing); }
    else if (e.key === 'ArrowRight') seek(store.state.day + (e.shiftKey ? 30 : 1));
    else if (e.key === 'ArrowLeft') seek(store.state.day - (e.shiftKey ? 30 : 1));
    else if (e.key === 'Home') seek(0);
    else if (e.key === 'End') seek(query.maxDay);
  });

  store.subscribe(function (s, ch) {
    if (ch.indexOf('selected') >= 0) renderSelection();
  });

  var rt = 0;
  root.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () { xmap.resize(); drawTimeline(); }, 120);
  });

  /* ── boot ─────────────────────────────────────────────────────────────── */

  el.legend.innerHTML = ['#f2d9a0','#ecc278','#e3a652','#d8853a','#c96a2e','#b35024','#97391b','#7a2c14']
    .map(function (c) { return '<i style="background:' + c + '"></i>'; }).join('');

  function boot(geo) {
    xmap.load(geo);
    query.setFilter(store.state.types, store.state.hazards);
    buildHazList();
    buildAxis();
    refreshCounts(true);
    drawTimeline();
    renderFeed();
    el.loading.style.display = 'none';
    ticker.add(tick);
    root.__DD_READY = true;
  }

  if (root.EXPLORE_GEO) {
    boot(root.EXPLORE_GEO);
  } else {
    console.error('Explorer: explore-geo.js missing');
    el.loading.innerHTML = '<div class="msg">Could not load the county map.</div>' +
      '<div class="muted" style="font-size:12px">Reload the page, or use the ' +
      '<a href="map.html" style="color:#004c53">classic map</a>.</div>';
  }

  root.__DD = { store: store, query: query, map: xmap, seek: seek, setPlaying: setPlaying, dates: dates };
})(window);
