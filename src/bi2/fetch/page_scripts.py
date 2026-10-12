"""JavaScript that the browser runs inside loaded pages."""

import json

# Elements found only on the pages of bot-check services: Akamai, Cloudflare, HUMAN
# (PerimeterX), DataDome and Imperva. Some of these pages say "200 OK".
_CHALLENGE = (
    "#sec-if-cpt-container, #challenge-running, #challenge-form, #cf-challenge-running, "
    "[id^='px-captcha'], iframe[src*='captcha-delivery.com'], iframe[src*='_Incapsula_Resource']"
)

# Bot checks that run in the page, like Cloudflare's "Just a moment...", show a page whose
# scripts move on to the real page once the check has passed. This is true when there's no such
# check to wait for: the page isn't a bot check's, and it isn't an error page with scripts to run.
NO_BOT_CHECK_RUNNING = """
() => {
  if (document.querySelector(CHALLENGE)) return false;
  const status = performance.getEntriesByType("navigation")[0]?.responseStatus ?? 0;
  const runs = (s) => !s.type || s.type === "module" || s.type.includes("javascript");
  return status < 400 || ![...document.scripts].some(runs);
}
""".replace("CHALLENGE", json.dumps(_CHALLENGE))

# The visible text of the header, the main content and the footer, as an expression. innerText
# leaves out text that CSS hides, such as a closed menu.
_REGION_TEXT = """(() => {
  const outermost = (selector) => [...document.querySelectorAll(selector)].filter(
    (el) => !el.parentElement?.closest(selector) && !el.closest("article"));
  const textOf = (elements) => elements.map((el) => el.innerText || "").join("\\n").trim();
  const header = textOf(outermost("header, [role=banner], #header, #site-header, .site-header"));
  const footer = textOf(outermost("footer, [role=contentinfo], #footer, #site-footer, .site-footer"));
  const mains = outermost("main, [role=main]");
  let main = mains.length ? textOf(mains) : (document.body ? document.body.innerText : "");
  if (!mains.length) for (const part of [header, footer]) if (part) main = main.replace(part, "");
  const limit = 20000;
  return { header: header.slice(0, limit), main: main.trim().slice(0, limit), footer: footer.slice(0, limit) };
})()"""

# Many pages draw their footer, which often holds the address and phone number, only while it's
# in view. This jumps to the bottom, reads the text there, then goes back to the top for the
# screenshot. It returns nothing when the whole page already fits on the screen.
SCROLL = """
async () => {
  const height = document.documentElement.scrollHeight;
  if (height <= window.innerHeight) return null;
  const pause = (ms) => new Promise((done) => setTimeout(done, ms));
  window.scrollTo(0, height);
  await pause(600);
  const seen = { page: performance.timeOrigin, text: REGION_TEXT };
  window.scrollTo(0, 0);
  await pause(300);
  return seen;
}
""".replace("REGION_TEXT", _REGION_TEXT)

# Reads the page in one go, so everything comes from the same page. Lists every image-like
# element with where it was drawn, whether it sits in the header, and whether it links to the
# home page. Lazy-loaded images report their real URL instead of the placeholder.
READ = """
() => {
  const absolute = (value) => { try { return new URL(value, location.href).href; } catch { return ""; } };
  const linksHome = (el) => {
    const link = el.closest("a[href]");
    if (!link) return false;
    try {
      const target = new URL(link.href, location.href);
      return target.origin === location.origin && (target.pathname === "/" || target.pathname === "");
    } catch { return false; }
  };
  const inHeader = (el) => !!el.closest("header, nav, [role=banner], [class*=header i], [id*=header i]");
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height };
  };
  const describe = (el, kind, url, alt) => ({
    kind, url, alt: alt || "", css_class: String(el.getAttribute("class") || ""),
    element_id: el.id || "", box: box(el), in_header: inHeader(el), links_home: linksHome(el),
  });
  const found = [];
  for (const img of document.images) {
    let url = img.currentSrc || img.src || "";
    if (url === location.href) url = "";  // an empty src makes the browser report the page itself
    if (!url || url.startsWith("data:")) {
      const lazy = img.dataset.src || img.dataset.lazySrc || img.getAttribute("data-original");
      if (lazy) url = absolute(lazy);
    }
    found.push(describe(img, "img", url, img.alt));
  }
  for (const svg of document.querySelectorAll("svg")) {
    const r = svg.getBoundingClientRect();
    if (r.width < 24 || r.height < 12) continue;  // icons, not logos
    const title = svg.querySelector("title");
    found.push(describe(svg, "svg", "", svg.getAttribute("aria-label") || (title ? title.textContent : "")));
  }
  for (const el of document.querySelectorAll("header *, nav *, [class*=logo i]")) {
    const match = getComputedStyle(el).backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
    if (match) found.push(describe(el, "background", absolute(match[1]), el.getAttribute("aria-label")));
  }
  const doctype = document.doctype ? new XMLSerializer().serializeToString(document.doctype) : "";
  return {
    page: performance.timeOrigin,  // different for every page the tab shows
    url: location.href,
    status: performance.getEntriesByType("navigation")[0]?.responseStatus ?? 0,
    html: doctype + (document.documentElement ? document.documentElement.outerHTML : ""),
    images: found.slice(0, 200),
    text: REGION_TEXT,
    challenge: !!document.querySelector(CHALLENGE),  // still a bot check's page
  };
}
""".replace("REGION_TEXT", _REGION_TEXT).replace("CHALLENGE", json.dumps(_CHALLENGE))

PAGE_ID = "() => performance.timeOrigin"
