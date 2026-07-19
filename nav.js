/*
  Disaster Data - shared site navigation
  ---------------------------------------
  This is the single source of truth for the top nav bar. Every page loads
  this one file, so the bar is identical on every page and only ever has to
  be changed here, in one place.

  To use it on a page, add this one line once, just before the closing body
  tag:

      <script src="/nav.js" defer></script>

  The script finds the page's existing nav and swaps in the shared bar. If a
  page has no nav at all, the bar is added at the top of the body instead.
  The current page is highlighted automatically from the URL, so there is
  nothing to set per page.

  Links use absolute paths (each starts with a /), which resolve the same way
  from any folder, including /states/. That is what lets the exact same bar
  work on every page without per-folder path edits.
*/
(function () {
  var LINKS = [
    { label: 'Overview',        href: '/' },
    { label: 'Explore',         href: '/#board' },
    { label: 'Map',             href: '/map.html' },
    { label: 'States',          href: '/states/' },
    { label: 'Funding',         href: '/public-assistance-projects.html' },
    { label: 'Denials',         href: '/denials.html' },
    { label: 'About',           href: '/about.html' },
    { label: 'Daily Ops Brief', href: '/ops-briefings/' }
  ];

  // Which link matches the current page, decided from the URL path.
  // Returns the index into LINKS, or -1 for no match (nothing highlighted).
  function activeIndex() {
    var p = location.pathname.replace(/\/index\.html$/, '/');
    if (p === '/' || p === '') return 0;                            // Overview (homepage)
    if (p.indexOf('/map.html') === 0) return 2;                     // Map
    if (p.indexOf('/states') === 0) return 3;                       // States and every state page
    if (p.indexOf('/public-assistance-projects') === 0) return 4;  // Funding
    if (p.indexOf('/denials') === 0) return 5;                      // Denials
    if (p.indexOf('/about') === 0) return 6;                        // About
    if (p.indexOf('/ops-briefings') === 0) return 7;               // Daily Ops Brief
    return -1;
  }

  var CSS = [
    '#dd-nav{position:sticky;top:0;z-index:50;background:rgba(246,241,231,.86);',
    '-webkit-backdrop-filter:saturate(140%) blur(10px);backdrop-filter:saturate(140%) blur(10px);',
    'border-bottom:1px solid #e0d8c5;display:flex;align-items:center;justify-content:space-between;',
    'padding:0 clamp(18px,4vw,48px);height:60px;box-sizing:border-box;',
    'font-family:"Public Sans",-apple-system,BlinkMacSystemFont,sans-serif;}',
    '#dd-nav *{box-sizing:border-box;}',
    '#dd-nav .dd-brand{font-family:"Fraunces",Georgia,serif;font-weight:600;font-size:19px;',
    'letter-spacing:-.4px;color:#004c53;text-decoration:none;}',
    '#dd-nav .dd-links{display:flex;align-items:center;gap:4px;}',
    '#dd-nav .dd-links a{font-size:13px;font-weight:500;color:#5b5346;text-decoration:none;',
    'padding:7px 12px;border-radius:6px;transition:.15s;letter-spacing:.2px;white-space:nowrap;}',
    '#dd-nav .dd-links a:hover{color:#1d1813;background:#f1ead9;}',
    '#dd-nav .dd-links a.on{color:#004c53;background:#d7e9ea;}',
    '@media(max-width:720px){#dd-nav{height:auto;flex-direction:column;align-items:stretch;',
    'justify-content:flex-start;gap:9px;padding-top:11px;padding-bottom:11px;}',
    '#dd-nav .dd-links{flex-wrap:wrap;gap:4px;}}'
  ].join('');

  function build() {
    if (document.getElementById('dd-nav')) return;

    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var nav = document.createElement('nav');
    nav.id = 'dd-nav';

    var brand = document.createElement('a');
    brand.className = 'dd-brand';
    brand.href = '/';
    brand.textContent = 'Disaster Data';
    nav.appendChild(brand);

    var list = document.createElement('div');
    list.className = 'dd-links';

    var active = activeIndex();
    LINKS.forEach(function (item, i) {
      var a = document.createElement('a');
      a.href = item.href;
      a.textContent = item.label;
      if (i === active) {
        a.className = 'on';
        a.setAttribute('aria-current', 'page');
      }
      list.appendChild(a);
    });
    nav.appendChild(list);

    // Replace whatever nav the page already has, keeping its position in the
    // page. If there is no existing nav, add ours at the top of the body.
    var existing = document.querySelector('nav');
    if (existing && existing.parentNode) {
      existing.parentNode.replaceChild(nav, existing);
    } else {
      document.body.insertBefore(nav, document.body.firstChild);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
