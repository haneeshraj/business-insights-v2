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
  // "instant", because pages that scroll smoothly would still be on their way back up when
  // the screenshot is taken.
  window.scrollTo({ top: height, behavior: "instant" });
  await pause(600);
  const seen = { page: performance.timeOrigin, text: REGION_TEXT };
  window.scrollTo({ top: 0, behavior: "instant" });
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
  // Home pages live at "/", at a language's home such as "/en", "/en-ca" or "/ca/en", or at a
  // home or index page under either: "/home", "/en/home.html", "/ca/en/homepage".
  const homePath = /^\\/(?:[a-z]{2}(?:[-_][a-z]{2})?(?:\\/[a-z]{2})?\\/?)?(?:(?:home(?:page)?|index)(?:\\.[a-z]{3,4})?\\/?)?$/i;
  // Pages built from web components keep parts of themselves, like Air Canada's header, in
  // shadow roots, which a plain search of the page doesn't reach. These search them too.
  const roots = [document];
  for (let i = 0; i < roots.length; i += 1) {
    for (const el of roots[i].querySelectorAll("*")) if (el.shadowRoot) roots.push(el.shadowRoot);
  }
  const all = (selector) => roots.flatMap((root) => [...root.querySelectorAll(selector)]);
  const closest = (el, selector) => {
    for (let node = el; node; ) {
      const found = node.closest(selector);
      if (found) return found;
      const root = node.getRootNode();
      node = root instanceof ShadowRoot ? root.host : null;
    }
    return null;
  };
  const linksHome = (el) => {
    const link = closest(el, "a[href]");
    if (!link) return false;
    try {
      const target = new URL(link.href, location.href);
      return target.origin === location.origin && homePath.test(target.pathname);
    } catch { return false; }
  };
  const inHeader = (el) => !!closest(el, "header, nav, [role=banner], [class*=header i], [id*=header i]");
  // What an element says about itself, and what the link around an image says about it, like
  // "Mejuri logo" or "wcb3-navigation-logo".
  const labelOf = (el) => ["aria-label", "title", "class", "id", "data-testid"]
    .map((name) => el.getAttribute(name) || "").join(" ").replace(/\\s+/g, " ").trim();
  const linkLabel = (el) => {
    const link = closest(el, "a[href]");
    return link ? labelOf(link).slice(0, 300) : "";
  };
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height };
  };
  const describe = (el, kind, url, alt) => ({
    kind, url, alt: alt || "", css_class: String(el.getAttribute("class") || ""),
    element_id: el.id || "", box: box(el), in_header: inHeader(el), links_home: linksHome(el),
    link_label: linkLabel(el),
  });
  // An inline SVG's code, standalone: the page's styles are written into it, the shapes it
  // borrows from elsewhere on the page are copied in, and scripts are left out, so it shows
  // the same when saved as a file of its own.
  const SVG_NS = "http://www.w3.org/2000/svg";
  const STYLES = ["fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
    "stroke-opacity", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "opacity", "display", "visibility", "clip-rule", "font-family",
    "font-size", "font-weight", "letter-spacing", "text-anchor"];
  const standalone = (svg) => {
    const clone = svg.cloneNode(true);
    const originals = [svg, ...svg.querySelectorAll("*")];
    const copies = [clone, ...clone.querySelectorAll("*")];
    originals.forEach((el, i) => {
      const style = getComputedStyle(el);
      copies[i].setAttribute("style", STYLES.map((name) => name + ":" + style.getPropertyValue(name)).join(";"));
      copies[i].removeAttribute("class");
    });
    const ids = new Set([...clone.querySelectorAll("[id]")].map((el) => el.id));
    const defs = document.createElementNS(SVG_NS, "defs");
    for (const use of clone.querySelectorAll("use")) {
      const ref = use.getAttribute("href") || use.getAttribute("xlink:href") || "";
      const shape = ref.startsWith("#") ? document.getElementById(ref.slice(1)) : null;
      if (shape && !ids.has(shape.id)) {
        defs.appendChild(shape.cloneNode(true));
        ids.add(shape.id);
      }
    }
    if (defs.childNodes.length) clone.insertBefore(defs, clone.firstChild);
    for (const el of clone.querySelectorAll("script, foreignObject")) el.remove();
    for (const el of [clone, ...clone.querySelectorAll("*")]) {
      for (const attribute of [...el.attributes]) {
        const value = attribute.value.trim().toLowerCase();
        if (attribute.name.startsWith("on") || value.startsWith("javascript:")) {
          el.removeAttribute(attribute.name);
        }
      }
    }
    const r = svg.getBoundingClientRect();
    clone.setAttribute("xmlns", SVG_NS);
    clone.setAttribute("width", String(Math.round(r.width)));
    clone.setAttribute("height", String(Math.round(r.height)));
    if (!clone.getAttribute("viewBox")) clone.setAttribute("viewBox", "0 0 " + r.width + " " + r.height);
    const code = new XMLSerializer().serializeToString(clone);
    return code.length <= 300000 ? code : "";
  };
  const found = [];
  const drawnBy = [];  // the element each found image is drawn by
  const add = (el, image) => { found.push(image); drawnBy.push(el); return image; };
  for (const img of all("img")) {
    let url = img.currentSrc || img.src || "";
    if (url === location.href) url = "";  // an empty src makes the browser report the page itself
    if (!url || url.startsWith("data:")) {
      const lazy = img.dataset.src || img.dataset.lazySrc || img.getAttribute("data-original");
      if (lazy) url = absolute(lazy);
    }
    add(img, describe(img, "img", url, img.alt));
  }
  // Inline SVGs. The code of the 8 likeliest to be the logo is kept, likeliest first, so a
  // header's icons don't use up the room before the logo.
  const drawings = [];
  for (const svg of all("svg")) {
    const r = svg.getBoundingClientRect();
    const title = svg.querySelector("title");
    const label = svg.getAttribute("aria-label") || (title ? title.textContent : "");
    // Icons aren't logos, but a small drawing labeled as the logo, or in a link that is, like
    // Mejuri's slim wordmark, can be.
    const labeled = /logo/i.test([label, labelOf(svg), linkLabel(svg)].join(" "));
    if (labeled ? r.width < 16 || r.height < 6 : r.width < 24 || r.height < 12) continue;
    // A picture drawn inside an SVG, like a profile picture, is that picture's own file.
    const picture = svg.querySelector("image");
    const href = picture ? picture.getAttribute("href") || picture.getAttribute("xlink:href") || "" : "";
    if (href && !href.startsWith("data:")) {
      add(svg, describe(svg, "img", absolute(href), label));
      continue;
    }
    const image = add(svg, describe(svg, "svg", "", label));
    const named = /logo/i.test([label, image.css_class, image.element_id, image.link_label].join(" "));
    const near = image.box.y < 400;
    const likely = 4 * named + 4 * image.links_home + 3 * (image.in_header && near) + near;
    if (likely) drawings.push([likely, svg, image]);
  }
  drawings.sort((a, b) => b[0] - a[0]);  // the sort is stable, so page order settles ties
  for (const [, svg, image] of drawings.slice(0, 8)) image.svg = standalone(svg);
  // Pictures set by CSS: backgrounds and masks, like Warby Parker's logo, on an element or
  // drawn before or after it.
  const urlOf = (value) => {
    const match = (value || "").match(/url\\(["']?(.*?)["']?\\)/);
    // url(#shape) points to a shape on the page itself, not to a picture.
    return match && !match[1].startsWith("#") ? absolute(match[1]) : "";
  };
  const styled = "header *, nav *, [class*=logo i], [class*=logo i] *, [aria-label*=logo i] *, [data-testid*=logo i] *";
  for (const el of all(styled)) {
    const urls = new Set();
    for (const pseudo of [null, "::before", "::after"]) {
      const style = getComputedStyle(el, pseudo);
      for (const value of [style.backgroundImage, style.maskImage, style.webkitMaskImage]) {
        const url = urlOf(value);
        if (url) urls.add(url);
      }
    }
    for (const url of urls) add(el, describe(el, "background", url, el.getAttribute("aria-label")));
  }
  // A logo drawn as styled text, like Uber's, has no picture of its own. A link home near the
  // top that says it's the logo or the home page, with no picture inside, is cut out of the
  // screenshot instead.
  for (const link of all("a[href]")) {
    if (!linksHome(link) || !/logo|home/i.test(labelOf(link))) continue;
    const r = link.getBoundingClientRect();
    if (r.width < 24 || r.height < 12 || r.y + window.scrollY > 300) continue;
    if (drawnBy.some((el) => el === link || link.contains(el))) continue;
    add(link, describe(link, "text", "", (link.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 100)));
  }
  // At most 200, keeping the ones that could be the logo before the rest of the page's
  // pictures, in page order.
  const promising = (image) => image.kind !== "img" || image.links_home || image.in_header
    || /logo/i.test([image.alt, image.css_class, image.link_label].join(" "));
  const kept = new Set([...new Set([...found.filter(promising), ...found])].slice(0, 200));
  const doctype = document.doctype ? new XMLSerializer().serializeToString(document.doctype) : "";
  return {
    page: performance.timeOrigin,  // different for every page the tab shows
    url: location.href,
    status: performance.getEntriesByType("navigation")[0]?.responseStatus ?? 0,
    html: doctype + (document.documentElement ? document.documentElement.outerHTML : ""),
    images: found.filter((image) => kept.has(image)),
    text: REGION_TEXT,
    challenge: !!document.querySelector(CHALLENGE),  // still a bot check's page
  };
}
""".replace("REGION_TEXT", _REGION_TEXT).replace("CHALLENGE", json.dumps(_CHALLENGE))

PAGE_ID = "() => performance.timeOrigin"
