"""The report's HTML page: its layout, styles and the filter script, and the script that
saves your checks on the review page."""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root { --bg: #f6f6f8; --card: #fff; --text: #1d1d22; --muted: #6b6b78; --line: #e2e2e8;
        --good: #1a7f37; --bad: #c62828; --warn: #9a6700; --accent: #3355dd; color-scheme: light; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121215; --card: #1b1b1f; --text: #ececf1; --muted: #9a9aa8; --line: #2c2c33;
          --good: #4ac26b; --bad: #ff6b6b; --warn: #d29922; --accent: #7c9bff; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0; overflow-wrap: anywhere; }
h3 { font-size: 13px; margin: 16px 0 8px; color: var(--muted); font-weight: 600; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.ok { color: var(--good); }
.miss { color: var(--bad); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line);
         vertical-align: top; overflow-wrap: anywhere; }
th { font-weight: 600; white-space: nowrap; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        padding: 16px; margin: 16px 0; }
.site-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 99px; border: 1px solid var(--line);
         color: var(--muted); white-space: nowrap; }
.badge.bad { color: var(--bad); border-color: currentColor; }
.badge.good { color: var(--good); border-color: currentColor; }
.grid { display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr); gap: 16px; }
@media (max-width: 760px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.shot img { width: 100%; border: 1px solid var(--line); border-radius: 6px; display: block; }
.facts th { width: 130px; color: var(--muted); }
.logos { display: flex; flex-wrap: wrap; gap: 8px; }
.logo { width: 172px; margin: 0; border: 1px solid var(--line); border-radius: 8px; padding: 6px;
        font-size: 12px; }
.logo.match { border-color: var(--good); box-shadow: inset 0 0 0 1px var(--good); }
.preview { height: 80px; display: flex; align-items: center; justify-content: center;
           border-radius: 4px; overflow: hidden;
           background: repeating-conic-gradient(#8881 0 25%, transparent 0 50%) 0 0 / 12px 12px; }
.preview img { max-width: 100%; max-height: 80px; }
figcaption { margin-top: 4px; overflow-wrap: anywhere; }
.checks { margin-top: 12px; }
.answers { margin-bottom: 8px; }
.answers th:first-child { width: 110px; color: var(--muted); }
.status { font-size: 12px; padding: 1px 8px; border-radius: 99px; white-space: nowrap;
          border: 1px solid currentColor; }
.status.ok { color: var(--good); }
.status.needs_review { color: var(--warn); }
.status.not_found { color: var(--muted); }
.status.error { color: var(--bad); }
.logo-pair { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px; }
.answer-logo { max-width: 160px; max-height: 64px; display: block; padding: 4px;
               border: 1px solid var(--line); border-radius: 4px; background: #fff; }
.answer-logo.on-dark { background: #1d1d22; }
.checks td:first-child { width: 24px; font-weight: 700; }
.share { width: 40%; }
.count { white-space: nowrap; }
.bar { display: inline-block; vertical-align: middle; width: 70%; height: 6px; margin-right: 8px;
       background: var(--line); border-radius: 3px; }
.bar span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--muted); }
pre { white-space: pre-wrap; font: 12px/1.4 ui-monospace, Consolas, monospace; max-height: 260px;
      overflow: auto; background: var(--bg); padding: 8px; border-radius: 6px; }
.controls { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin: 16px 0 0; }
input[type=search] { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px;
                     background: var(--card); color: var(--text); width: min(320px, 100%); }
.check { min-width: 240px; }
.check button { font: inherit; font-size: 12px; padding: 2px 10px; margin: 0 4px 4px 0;
                border: 1px solid var(--line); border-radius: 6px; background: var(--card);
                color: var(--text); cursor: pointer; }
.check button[data-verdict=right][aria-pressed=true] { background: var(--good);
                                                       border-color: var(--good); color: var(--card); }
.check button[data-verdict=wrong][aria-pressed=true] { background: var(--bad);
                                                       border-color: var(--bad); color: var(--card); }
.check input { display: block; width: 100%; padding: 3px 6px; border: 1px solid var(--line);
               border-radius: 6px; background: var(--card); color: var(--text); font: inherit;
               font-size: 12px; }
.check input + input { margin-top: 4px; }
.check input[hidden] { display: none; }
.check.saving { opacity: 0.5; }
.check .label { margin-top: 4px; font-size: 12px; }
.group { padding: 0 6px; border-radius: 99px; border: 1px solid currentColor; white-space: nowrap; }
.group.tp { color: var(--good); }
.group.fp { color: var(--bad); }
.group.fn { color: var(--warn); }
.group.tn { color: var(--muted); }
#learned table { margin-bottom: 8px; }
.groups td, .records td { white-space: nowrap; }
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<div class="muted">{subtitle}</div>
{summary}
<div class="controls">
  <input type="search" id="search" placeholder="Filter by address" aria-label="Filter by address">
  <label><input type="checkbox" id="misses"> Only sites that miss a gold answer</label>
  {controls}
</div>
{sites}
</main>
<script nonce="{nonce}">
const search = document.getElementById("search");
const missesOnly = document.getElementById("misses");
const uncheckedOnly = document.getElementById("unchecked");  // only on the review page
function filter() {
  const words = search.value.trim().toLowerCase();
  for (const site of document.querySelectorAll(".site")) {
    site.hidden = !site.dataset.url.includes(words)
      || (missesOnly.checked && site.dataset.misses === "0")
      || (uncheckedOnly !== null && uncheckedOnly.checked && site.dataset.unchecked === "0");
  }
}
search.addEventListener("input", filter);
missesOnly.addEventListener("change", filter);
uncheckedOnly?.addEventListener("change", filter);
</script>
{review}
</body>
</html>
"""

UNCHECKED_FILTER = '<label><input type="checkbox" id="unchecked"> Only sites with answers no one has checked</label>'

# Saves a check when you press Right or Wrong, or change the note of an answer you've marked,
# then shows what the server sends back: every answer's label, and the summary rebuilt.
REVIEW_SCRIPT = """<script nonce="{nonce}" data-token="{token}">
(() => {
  const token = document.currentScript.dataset.token;
  const key = (site, field) => JSON.stringify([site, field]);
  const cells = new Map();
  for (const cell of document.querySelectorAll("td.check")) {
    cells.set(key(cell.dataset.site, cell.dataset.field), cell);
  }

  function show(answers) {
    const unchecked = new Map();
    for (const answer of answers) {
      const cell = cells.get(key(answer.site, answer.field));
      if (cell === undefined) continue;
      for (const button of cell.querySelectorAll("button")) {
        button.setAttribute("aria-pressed", String(button.dataset.verdict === answer.verdict));
      }
      const correct = cell.querySelector(".correct");
      correct.hidden = answer.verdict !== "wrong";
      if (document.activeElement !== correct) correct.value = answer.correct;
      cell.querySelector(".label").innerHTML = answer.label;  // built and escaped by the server
      const site = cell.closest(".site");
      unchecked.set(site, (unchecked.get(site) ?? 0) + (answer.by === "" ? 1 : 0));
    }
    for (const [site, count] of unchecked) site.dataset.unchecked = String(count);
  }

  async function save(cell, verdict) {
    const label = cell.querySelector(".label");
    const correct = cell.querySelector(".correct");
    cell.classList.add("saving");
    try {
      const response = await fetch("/checks", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Review-Token": token},
        body: JSON.stringify({
          site: cell.dataset.site,
          field: cell.dataset.field,
          verdict,
          note: cell.querySelector(".note").value,
          correct: verdict === "wrong" ? correct.value : "",
        }),
      }).catch(() => { throw new Error("is bi2 review still running?"); });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      show(data.answers);
      document.getElementById("learned").outerHTML = data.summary;
      filter();
      if (verdict === "wrong" && correct.value === "") correct.focus();
    } catch (error) {
      label.textContent = "Not saved: " + error.message;
    } finally {
      cell.classList.remove("saving");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("td.check button");
    if (button !== null) save(button.closest("td.check"), button.dataset.verdict);
  });
  document.addEventListener("change", (event) => {
    if (!event.target.matches("td.check input")) return;
    const cell = event.target.closest("td.check");
    const marked = cell.querySelector("button[aria-pressed=true]");
    if (marked !== null) save(cell, marked.dataset.verdict);
    else cell.querySelector(".label").textContent = "Press one of the buttons first, to save the note.";
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("td.check input")) event.target.blur();
  });
})();
</script>"""
