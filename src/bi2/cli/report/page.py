"""The report's HTML page: its layout, styles and the filter script."""

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
.answer-logo { max-width: 220px; max-height: 64px; display: block; margin-bottom: 4px;
               background: repeating-conic-gradient(#8881 0 25%, transparent 0 50%) 0 0 / 12px 12px; }
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
</div>
{sites}
</main>
<script>
const search = document.getElementById("search");
const missesOnly = document.getElementById("misses");
function filter() {
  const words = search.value.trim().toLowerCase();
  for (const site of document.querySelectorAll(".site")) {
    site.hidden = !site.dataset.url.includes(words)
      || (missesOnly.checked && site.dataset.misses === "0");
  }
}
search.addEventListener("input", filter);
missesOnly.addEventListener("change", filter);
</script>
</body>
</html>
"""
