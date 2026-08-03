/* nav.js — shared navigation behaviour.
   Every page ships its own <nav> markup, so this script's only job is to make the
   highlight correct rather than hard-coded: it finds the link matching the page
   you are actually on and marks it active. Harmless on any page that already got
   it right, and it means a page copied from another one does not end up
   highlighting the wrong tab. */
(function () {
  'use strict';

  var nav = document.querySelector('.navlinks');
  if (!nav) return;

  /* "/states/index.html" and "/states/" are the same page; so are "/" and "/index.html". */
  function normalise(path) {
    path = (path || '').replace(/\/index\.html$/, '/');
    if (path.charAt(path.length - 1) !== '/' && path.indexOf('.') === -1) path += '/';
    return path === '' ? '/' : path;
  }

  var here = normalise(location.pathname);
  var links = nav.querySelectorAll('a');
  var match = null;

  for (var i = 0; i < links.length; i++) {
    var href = links[i].getAttribute('href') || '';
    /* Skip anything with a fragment. "#board" and "index.html#board" both point at a
       section rather than a page, and neither should ever claim the highlight — on the
       homepage they would otherwise beat the "Overview" link to it. */
    if (href.indexOf('#') !== -1) continue;
    var target;
    try { target = normalise(new URL(href, location.href).pathname); } catch (e) { continue; }
    if (target === here) { match = links[i]; break; }
  }

  /* No match usually means the current page marks itself with href="#" (the homepage and
     the map both do). Trust the hard-coded highlight in that case and only add the
     screen-reader hint it is missing. */
  if (!match) match = nav.querySelector('a.on');
  if (!match) return;

  for (var j = 0; j < links.length; j++) {
    links[j].classList.remove('on');
    links[j].removeAttribute('aria-current');
  }
  match.classList.add('on');
  match.setAttribute('aria-current', 'page');
})();
