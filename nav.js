/* ----------------------------------------------------------------------------
   nav.js  -  the one and only Disaster Data header.

   Every page on the site loads this file and defines no nav of its own.
   To change the bar everywhere, edit ITEMS below and redeploy this one file.
   Nothing else on the site needs to be touched, including generated pages.

   Add it to a page as the first thing inside <body>:
     <script src="/nav.js"></script>
---------------------------------------------------------------------------- */
(function () {
  "use strict";

  /* ---- the nav. This list is the only thing you should ever need to edit. -- */
  var BRAND = "Disaster Data";
  var BRAND_HREF = "/";
  var ITEMS = [
    ["Overview", "/"],
    ["Explore",  "/explore.html"],
    ["Map",      "/map.html"],
    ["Compare",  "/compare.html"],
    ["States",   "/states/"],
    ["Local",    "/jurisdiction.html"],
    ["Funding",  "/public-assistance-projects.html"],
    ["Denials",  "/denials.html"],
    ["About",    "/about.html"]
  ];
  /* -------------------------------------------------------------------------- */

  var CSS = [
    "#ddnav{position:sticky;top:0;z-index:1100;box-sizing:border-box;display:flex;flex-direction:row;flex-wrap:nowrap;align-items:center;justify-content:space-between;gap:14px;width:100%;height:60px;margin:0;padding:0 clamp(16px,4vw,48px);padding-top:0;padding-bottom:0;background:rgba(246,241,231,.93);-webkit-backdrop-filter:saturate(140%) blur(10px);backdrop-filter:saturate(140%) blur(10px);border:0;border-bottom:1px solid #e0d8c5;font-family:'Public Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}",
    "#ddnav *,#ddmenu *{box-sizing:border-box;}",
    "#ddnav .ddbrand{flex:0 0 auto;display:inline-block;font-family:'Fraunces',Georgia,serif;font-size:19px;font-weight:600;line-height:1.2;letter-spacing:-.4px;color:#004c53;text-decoration:none;white-space:nowrap;}",
    "#ddnav .ddbrand:hover,#ddnav .ddbrand:focus{color:#0a6b73;text-decoration:none;}",
    "#ddnav .ddlinks{display:flex;align-items:center;gap:2px;min-width:0;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;-ms-overflow-style:none;-webkit-overflow-scrolling:touch;}",
    "#ddnav .ddlinks::-webkit-scrollbar{display:none;}",
    "#ddnav .ddlinks a{display:block;font-family:inherit;font-size:13px;font-weight:500;line-height:1.2;letter-spacing:.2px;color:#5b5346;text-decoration:none;white-space:nowrap;padding:7px 10px;border-radius:6px;transition:background .15s,color .15s;}",
    "#ddnav .ddlinks a:hover{color:#1d1813;background:#f1ead9;text-decoration:none;}",
    "#ddnav .ddlinks a[aria-current=\"page\"]{color:#004c53;background:#d7e9ea;font-weight:600;}",
    "#ddnav .ddburger{flex:0 0 auto;display:none;flex-direction:column;justify-content:center;gap:5px;width:40px;height:40px;padding:8px;margin:0;background:none;border:0;border-radius:8px;cursor:pointer;}",
    "#ddnav .ddburger span{display:block;width:100%;height:2px;background:#1d1813;border-radius:2px;transition:transform .2s,opacity .2s;}",
    "#ddnav .ddburger[aria-expanded=\"true\"] span:nth-child(1){transform:translateY(7px) rotate(45deg);}",
    "#ddnav .ddburger[aria-expanded=\"true\"] span:nth-child(2){opacity:0;}",
    "#ddnav .ddburger[aria-expanded=\"true\"] span:nth-child(3){transform:translateY(-7px) rotate(-45deg);}",
    "#ddnav a:focus-visible,#ddnav button:focus-visible,#ddmenu a:focus-visible{outline:2px solid #004c53;outline-offset:2px;}",
    "#ddmenu{display:none;}",
    "@media(max-width:900px){",
    "#ddnav .ddlinks{display:none;}",
    "#ddnav .ddburger{display:flex;}",
    "#ddmenu:not([hidden]){position:sticky;top:60px;z-index:1099;display:flex;flex-direction:column;gap:2px;width:100%;margin:0;padding:10px clamp(16px,4vw,48px) 16px;background:#f6f1e7;border-bottom:1px solid #e0d8c5;font-family:'Public Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}",
    "#ddmenu a{display:block;font-size:15px;font-weight:500;line-height:1.3;color:#1d1813;text-decoration:none;padding:11px 12px;border-radius:8px;}",
    "#ddmenu a:hover{background:#f1ead9;text-decoration:none;}",
    "#ddmenu a[aria-current=\"page\"]{color:#004c53;background:#d7e9ea;font-weight:600;}",
    "}"
  ].join("\n");

  /* Normalize a path so /states/index.html, /states/ and states/ all compare
     equal, and so a link can be matched by prefix for section roots. */
  function norm(p) {
    p = (p || "").split("#")[0].split("?")[0].toLowerCase();
    p = p.replace(/index\.html$/, "");
    if (p.charAt(0) !== "/") { p = "/" + p; }
    return p === "" ? "/" : p;
  }

  function build() {
    if (document.getElementById("ddnav")) { return; }

    if (!document.getElementById("ddnav-css")) {
      var style = document.createElement("style");
      style.id = "ddnav-css";
      style.appendChild(document.createTextNode(CSS));
      (document.head || document.documentElement).appendChild(style);
    }

    var here = norm(location.pathname);

    function makeLink(label, href) {
      var a = document.createElement("a");
      a.setAttribute("href", href);
      a.appendChild(document.createTextNode(label));
      var t = norm(href);
      var onIt = (t === here) ||
                 (t !== "/" && t.charAt(t.length - 1) === "/" && here.indexOf(t) === 0);
      if (onIt) { a.setAttribute("aria-current", "page"); }
      return a;
    }

    var nav = document.createElement("nav");
    nav.id = "ddnav";
    nav.setAttribute("aria-label", "Primary");

    var brand = document.createElement("a");
    brand.className = "ddbrand";
    brand.setAttribute("href", BRAND_HREF);
    brand.appendChild(document.createTextNode(BRAND));
    nav.appendChild(brand);

    var links = document.createElement("div");
    links.className = "ddlinks";
    var menu = document.createElement("div");
    menu.id = "ddmenu";
    menu.setAttribute("hidden", "");

    for (var i = 0; i < ITEMS.length; i++) {
      links.appendChild(makeLink(ITEMS[i][0], ITEMS[i][1]));
      menu.appendChild(makeLink(ITEMS[i][0], ITEMS[i][1]));
    }
    nav.appendChild(links);

    var burger = document.createElement("button");
    burger.className = "ddburger";
    burger.setAttribute("type", "button");
    burger.setAttribute("aria-label", "Menu");
    burger.setAttribute("aria-expanded", "false");
    burger.setAttribute("aria-controls", "ddmenu");
    for (var j = 0; j < 3; j++) { burger.appendChild(document.createElement("span")); }
    burger.addEventListener("click", function () {
      var open = burger.getAttribute("aria-expanded") === "true";
      burger.setAttribute("aria-expanded", open ? "false" : "true");
      if (open) { menu.setAttribute("hidden", ""); }
      else { menu.removeAttribute("hidden"); }
    });
    nav.appendChild(burger);

    /* Insert at the very top of the body, wherever the script tag happens
       to sit, so the bar is always the first thing on the page. */
    var first = document.body.firstChild;
    document.body.insertBefore(menu, first);
    document.body.insertBefore(nav, menu);
  }

  if (document.body) { build(); }
  else { document.addEventListener("DOMContentLoaded", build); }
})();
