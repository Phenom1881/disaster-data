/* Disaster Data — Explorer story mode.

   A story is just a scripted sequence of store states. Each section carries a keyframe;
   an IntersectionObserver applies it as the section scrolls into view, and the cursor
   tweens so the map animates between beats rather than jumping.

   One honesty rule runs through every caption: this dataset records the date a federal
   declaration was SIGNED, not the date the disaster struck. Fire-management declarations
   are same-day; major-disaster declarations often lag by weeks. Captions say "declared",
   never "hit". */
(function (root) {
  'use strict';

  var DD = root.DD;

  /* Day helpers are bound at init (they need the payload epoch). */
  function makeBeats(dates, maxDay) {
    function d(y, m, day) { return dates.dayOf(y, m, day); }
    return [
      {
        id: 'intro',
        title: 'Twenty-five years, one map',
        body: 'Every federal disaster declaration since 1999, placed on the county it covered. ' +
              '48,607 county-level records. Scroll to walk through the moments that shaped them.',
        kf: { winA: 0, winB: maxDay, cursor: maxDay, brushed: false, geo: null }
      },
      {
        id: 'katrina',
        title: 'Katrina, and the evacuation that followed',
        body: 'In the six weeks shown here, <b>67 declarations</b> reached <b>3,071 counties</b>. ' +
              'Many were not for wind or water damage at all: declarations titled for Katrina ' +
              'alone touched <b>47 states</b>, because evacuation declarations followed people ' +
              'inland. On 10 September 2005, 777 county records were created in a single day.',
        kf: { winA: d(2005, 8, 20), winB: d(2005, 9, 30), cursor: d(2005, 9, 30), brushed: true, geo: null }
      },
      {
        id: 'rita',
        title: 'Three weeks later, Rita',
        body: 'Scoped to Texas, Rita is two declarations — covering all <b>254 Texas counties</b> ' +
              'at once. Statewide declarations are why one event can paint an entire state in a ' +
              'single day, and why county counts and declaration counts tell different stories.',
        kf: { winA: d(2005, 9, 20), winB: d(2005, 9, 30), cursor: d(2005, 9, 30), brushed: true,
              geo: { state: '48' } }
      },
      {
        id: 'sandy',
        title: 'Sandy runs up the coast',
        body: 'From late October 2012, <b>25 declarations</b> across <b>409 counties</b>. The ' +
              'worst damage was concentrated on the New Jersey and New York coast, but the ' +
              'declarations reached well inland.',
        kf: { winA: d(2012, 10, 25), winB: d(2012, 12, 31), cursor: d(2012, 12, 31), brushed: true, geo: null }
      },
      {
        id: 'covid',
        title: 'March 2020: the whole country at once',
        body: '<b>13 March 2020 produced 3,232 county records in a single day</b> — the largest ' +
              'day in the entire record, by a wide margin. Within six weeks, <b>120 declarations</b> ' +
              'had reached <b>3,234 counties</b>, essentially the whole country. Nothing else in ' +
              'twenty-five years looks remotely like it.',
        kf: { winA: d(2020, 3, 1), winB: d(2020, 4, 17), cursor: d(2020, 4, 17), brushed: true, geo: null }
      },
      {
        id: 'helene',
        title: 'Helene, and the mountains',
        body: 'On 26 September 2024, <b>375 county records</b> were created in a single day. ' +
              'Helene’s worst damage was hundreds of miles inland, in the southern Appalachians — ' +
              'a reminder that hurricane risk does not stop at the coast.',
        kf: { winA: d(2024, 9, 20), winB: d(2024, 12, 31), cursor: d(2024, 12, 31), brushed: true, geo: null }
      },
      {
        id: 'money',
        title: 'Follow the money',
        body: 'FEMA has obligated <b>$284.5 billion</b> in Public Assistance across these ' +
              'disasters, and it is nothing like evenly spread: Hurricane Maria alone accounts ' +
              'for <b>$36B in Puerto Rico</b> and <b>$22B in the U.S. Virgin Islands</b>. ' +
              'Dollars are dated by disaster, so this map is state-level — FEMA does not publish ' +
              'county obligations by date.',
        kf: { winA: 0, winB: maxDay, cursor: maxDay, brushed: false, geo: null,
              measure: 'dollars', moneyGeo: 'state' }
      },
      {
        id: 'end',
        title: 'Now take it apart yourself',
        body: 'Brush any range on the timeline, click a county to scope to it, switch hazards ' +
              'on and off. Every view filters every other view.',
        kf: { winA: 0, winB: maxDay, cursor: maxDay, brushed: false, geo: null, measure: 'events' }
      }
    ];
  }

  function Story(opts) {
    this.host = opts.host;
    this.apply = opts.apply;          /* fn(keyframe, animate) */
    this.onExit = opts.onExit;
    this.dates = opts.dates;
    this.beats = makeBeats(opts.dates, opts.maxDay);
    this.active = -1;
    this._build();
  }

  Story.prototype._build = function () {
    var html = '<div class="story-note">These are the dates federal aid was <b>declared</b>, ' +
               'not the dates disasters struck. Fire declarations are same-day; major-disaster ' +
               'declarations often lag by weeks.</div>';
    html += this.beats.map(function (b, i) {
      return '<section class="beat" data-i="' + i + '">' +
        '<h2>' + b.title + '</h2><p>' + b.body + '</p></section>';
    }).join('');
    html += '<div class="story-end"><button class="ghost" id="story-exit">Explore freely →</button></div>';
    this.host.innerHTML = html;

    var self = this;
    var exit = document.getElementById('story-exit');
    if (exit) exit.addEventListener('click', function () { self.onExit && self.onExit(); });

    this.sections = [].slice.call(this.host.querySelectorAll('.beat'));
    if (!('IntersectionObserver' in root)) {          /* no observer: show them all, no motion */
      this.sections.forEach(function (s) { s.classList.add('on'); });
      return;
    }
    this.io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var i = +e.target.dataset.i;
        e.target.classList.add('on');
        if (i !== self.active) { self.active = i; self.apply(self.beats[i].kf, true); }
      });
    }, { rootMargin: '-45% 0px -45% 0px', threshold: 0 });
    this.sections.forEach(function (s) { self.io.observe(s); });
  };

  Story.prototype.destroy = function () {
    if (this.io) this.io.disconnect();
    this.host.innerHTML = '';
    this.active = -1;
  };
  Story.prototype.first = function () {
    if (this.beats.length) { this.active = 0; this.apply(this.beats[0].kf, false); }
  };

  root.DD.Story = Story;
})(window);
