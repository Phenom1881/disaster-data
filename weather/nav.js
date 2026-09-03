(function () {
  "use strict";

  var ITEMS = [
    ["Overview", "/"],
    ["Explore", "/explore.html"],
    ["Map", "/map.html"],
    ["Compare", "/compare.html"],
    ["States", "/states/"],
    ["Local", "/jurisdiction.html"],
    ["Weather", "/weather/"],
    ["Funding", "/public-assistance-projects.html"],
    ["Mitigation", "/mitigation.html"],
    ["Denials", "/denials.html"],
    ["About", "/about.html"]
  ];

  var CSS = [
    "#ddnav{position:sticky;top:0;z-index:1100;box-sizing:border-box;display:flex;flex-flow:row nowrap;align-items:center;justify-content:space-between;gap:14px;width:100%;height:60px;margin:0;padding:0 clamp(16px,4vw,48px);background:rgba(246,241,231,.93);-webkit-backdrop-filter:saturate(140%) blur(10px);backdrop-filter:saturate(140%) blur(10px);border-bottom:1px solid #e0d8c5;font-family:'Public Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}",
    "#ddnav *,#ddmenu *{box-sizing:border-box}",
    "#ddnav .ddbrand{flex:0 0 auto;font-family:'Fraunces',Georgia,serif;font-size:19px;font-weight:600;letter-spacing:-.4px;color:#004c53;text-decoration:none;white-space:nowrap}",
    "#ddnav .ddbrand:hover,#ddnav .ddbrand:focus{color:#0a6b73}",
    "#ddnav .ddlinks{display:flex;align-items:center;gap:2px;min-width:0;overflow-x:auto;scrollbar-width:none}",
    "#ddnav .ddlinks::-webkit-scrollbar{display:none}",
    "#ddnav .ddlinks a{display:block;font-size:13px;font-weight:500;letter-spacing:.2px;color:#5b5346;text-decoration:none;white-space:nowrap;padding:7px 10px;border-radius:6px}",
    "#ddnav .ddlinks a:hover{color:#1d1813;background:#f1ead9}",
    "#ddnav .ddlinks a[aria-current='page']{color:#004c53;background:#d7e9ea;font-weight:600}",
    "#ddnav .ddburger{display:none;flex-direction:column;justify-content:center;gap:5px;width:40px;height:40px;padding:8px;background:none;border:0;border-radius:8px;cursor:pointer}",
    "#ddnav .ddburger span{display:block;width:100%;height:2px;background:#1d1813;border-radius:2px;transition:transform .2s,opacity .2s}",
    "#ddnav .ddburger[aria-expanded='true'] span:nth-child(1){transform:translateY(7px) rotate(45deg)}",
    "#ddnav .ddburger[aria-expanded='true'] span:nth-child(2){opacity:0}",
    "#ddnav .ddburger[aria-expanded='true'] span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}",
    "#ddnav a:focus-visible,#ddnav button:focus-visible,#ddmenu a:focus-visible{outline:2px solid #004c53;outline-offset:2px}",
    "#ddmenu{display:none}",
    "@media(max-width:900px){#ddnav .ddlinks{display:none}#ddnav .ddburger{display:flex}#ddmenu:not([hidden]){position:sticky;top:60px;z-index:1099;display:flex;flex-direction:column;gap:2px;width:100%;padding:10px clamp(16px,4vw,48px) 16px;background:#f6f1e7;border-bottom:1px solid #e0d8c5;font-family:'Public Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}#ddmenu a{display:block;font-size:15px;font-weight:500;color:#1d1813;text-decoration:none;padding:11px 12px;border-radius:8px}#ddmenu a:hover{background:#f1ead9}#ddmenu a[aria-current='page']{color:#004c53;background:#d7e9ea;font-weight:600}}"
  ].join("\n");

  function norm(path) {
    path = (path || "").split("#")[0].split("?")[0].toLowerCase().replace(/index\.html$/, "");
    if (path.charAt(0) !== "/") path = "/" + path;
    return path || "/";
  }

  function build() {
    if (document.getElementById("ddnav")) return;
    var style = document.createElement("style");
    style.id = "ddnav-css";
    style.textContent = CSS;
    document.head.appendChild(style);

    var here = norm(location.pathname);
    function makeLink(item) {
      var link = document.createElement("a");
      link.href = item[1];
      link.textContent = item[0];
      var target = norm(item[1]);
      if (target === here || (target !== "/" && target.endsWith("/") && here.indexOf(target) === 0)) {
        link.setAttribute("aria-current", "page");
      }
      return link;
    }

    var nav = document.createElement("nav");
    nav.id = "ddnav";
    nav.setAttribute("aria-label", "Primary");
    var brand = document.createElement("a");
    brand.className = "ddbrand";
    brand.href = "/";
    brand.textContent = "Disaster Data";
    nav.appendChild(brand);

    var links = document.createElement("div");
    links.className = "ddlinks";
    var menu = document.createElement("div");
    menu.id = "ddmenu";
    menu.hidden = true;
    ITEMS.forEach(function (item) {
      links.appendChild(makeLink(item));
      menu.appendChild(makeLink(item));
    });
    nav.appendChild(links);

    var burger = document.createElement("button");
    burger.className = "ddburger";
    burger.type = "button";
    burger.setAttribute("aria-label", "Menu");
    burger.setAttribute("aria-expanded", "false");
    burger.setAttribute("aria-controls", "ddmenu");
    for (var i = 0; i < 3; i += 1) burger.appendChild(document.createElement("span"));
    burger.addEventListener("click", function () {
      var open = burger.getAttribute("aria-expanded") === "true";
      burger.setAttribute("aria-expanded", String(!open));
      menu.hidden = open;
    });
    nav.appendChild(burger);

    document.body.insertBefore(menu, document.body.firstChild);
    document.body.insertBefore(nav, menu);
  }

  if (document.body) build();
  else document.addEventListener("DOMContentLoaded", build);
})();
