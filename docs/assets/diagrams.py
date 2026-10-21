"""The docs' diagrams, drawn as SVG in the style of architecture.svg.

    uv run python docs/assets/diagrams.py

writes each diagram below to docs/assets/<name>.svg. A diagram is boxes, questions, stores,
groups and arrows placed by hand: change one and run this again. architecture.svg itself is
drawn by hand.
"""

from dataclasses import dataclass
from html import escape
from itertools import pairwise
from pathlib import Path

FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
NAVY = "#0b1f3a"
INK = "#334155"
MUTED = "#475569"
LINE = "#cbd5e1"
PAPER = "#f1f5f9"
PANEL = "#e2e8f0"
ACCENT = {
    "green": "#16a34a",
    "cyan": "#0891b2",
    "purple": "#7c3aed",
    "orange": "#ea580c",
    "blue": "#2563eb",
}
# The fill, border, title color and text color of each kind of box.
KINDS = {
    "box": ("#ffffff", LINE, NAVY, INK),
    "start": (NAVY, NAVY, "#f8fafc", "#cbd5e1"),
    "good": ("#dcfce7", "#16a34a", "#14532d", "#166534"),
    "bad": ("#fee2e2", "#f87171", "#7f1d1d", "#991b1b"),
    "warn": ("#fef3c7", "#f59e0b", "#78350f", "#92400e"),
    "later": ("#ffffff", "#94a3b8", NAVY, INK),
    "ask": ("#eff6ff", "#60a5fa", "#1e3a8a", "#1e40af"),
}
TITLE_SIZE, TEXT_SIZE, LABEL_SIZE = 16, 13.5, 12.5
TITLE_STEP, TEXT_STEP = 22, 19
# A list item's second line starts under the item's words, not under its bullet. No-break
# spaces, since SVG text drops leading ordinary ones.
INDENT = chr(0xA0) * 3

type Point = tuple[float, float]
type Place = tuple[float, float, float, float]


@dataclass(frozen=True)
class Box:
    """Where a box was drawn, and the points on its sides that arrows start and end at."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def top(self, dx: float = 0) -> Point:
        return (self.cx + dx, self.y)

    def bottom(self, dx: float = 0) -> Point:
        return (self.cx + dx, self.y + self.h)

    def left(self, dy: float = 0) -> Point:
        return (self.x, self.cy + dy)

    def right(self, dy: float = 0) -> Point:
        return (self.x + self.w, self.cy + dy)


def _length(stretch: tuple[Point, Point]) -> float:
    (ax, ay), (bx, by) = stretch
    return abs(ax - bx) + abs(ay - by)


class Diagram:
    """One SVG: a heading, then groups, arrows, boxes and labels, each drawn over the ones
    before it."""

    def __init__(self, name: str, size: tuple[int, int], title: str, subtitle: str) -> None:
        self.name = name
        self.width, self.height = size
        self.title, self.subtitle = title, subtitle
        self.groups: list[str] = []
        self.arrows: list[str] = []
        self.boxes: list[str] = []
        self.labels: list[str] = []

    def _text(
        self,
        box: Box,
        title: str,
        lines: tuple[str, ...],
        colors: tuple[str, str],
        align: str = "middle",
        inset: float = 0,
    ) -> str:
        """A bold title and the lines under it, centered on the box as one block. A newline
        breaks the title."""
        title_color, text_color = colors
        titles = title.split("\n") if title else []
        y = box.cy - (TITLE_STEP * len(titles) + TEXT_STEP * len(lines)) / 2 + 15
        x = box.cx if align == "middle" else box.x + inset
        out = []
        for text in titles:
            out.append(
                f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{align}" font-size="{TITLE_SIZE}" '
                f'font-weight="700" fill="{title_color}">{escape(text)}</text>'
            )
            y += TITLE_STEP
        for text in lines:
            out.append(
                f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{align}" font-size="{TEXT_SIZE}" '
                f'fill="{text_color}">{escape(text)}</text>'
            )
            y += TEXT_STEP
        return "\n".join(out)

    def box(
        self,
        place: Place,
        title: str,
        *lines: str,
        kind: str = "box",
        accent: str | None = None,
        align: str = "middle",
    ) -> Box:
        """A step or a thing, at (x, y, width, height). `accent` draws a colored bar down its
        left side."""
        b = Box(*place)
        fill, border, title_color, text_color = KINDS[kind]
        dash = ' stroke-dasharray="6 5"' if kind == "later" else ""
        parts = [
            f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="12" fill="{fill}" '
            f'stroke="{border}" stroke-width="1.5"{dash}/>'
        ]
        if accent:
            parts.append(
                f'<rect x="{b.x}" y="{b.y}" width="10" height="{b.h}" rx="5" '
                f'fill="{ACCENT[accent]}"/>'
            )
        inset = 26 if accent else 20
        parts.append(self._text(b, title, lines, (title_color, text_color), align, inset))
        self.boxes.append("\n".join(parts))
        return b

    def ask(self, place: Place, title: str, *lines: str) -> Box:
        """A question the flow branches on, marked with a question mark."""
        b = Box(*place)
        fill, border, title_color, text_color = KINDS["ask"]
        mark = b.x + 22
        words = Box(b.x + 30, b.y, b.w - 30, b.h)
        self.boxes.append(
            f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="12" fill="{fill}" '
            f'stroke="{border}" stroke-width="1.5"/>\n'
            f'<circle cx="{mark}" cy="{b.cy}" r="11" fill="{ACCENT["blue"]}"/>\n'
            f'<text x="{mark}" y="{b.cy + 5}" text-anchor="middle" font-size="14" '
            f'font-weight="800" fill="#ffffff">?</text>\n'
            + self._text(words, title, lines, (title_color, text_color))
        )
        return b

    def store(self, place: Place, title: str, *lines: str) -> Box:
        """Where things are kept, drawn as a cylinder."""
        b = Box(*place)
        ry = 9
        side = b.h - 2 * ry
        self.boxes.append(
            f'<path d="M{b.x} {b.y + ry} v{side} a{b.w / 2} {ry} 0 0 0 {b.w} 0 v-{side}" '
            f'fill="#ffffff" stroke="{LINE}" stroke-width="1.5"/>\n'
            f'<ellipse cx="{b.cx}" cy="{b.y + ry}" rx="{b.w / 2}" ry="{ry}" fill="#f8fafc" '
            f'stroke="{LINE}" stroke-width="1.5"/>\n'
            + self._text(Box(b.x, b.y + ry, b.w, b.h - ry), title, lines, (NAVY, INK))
        )
        return b

    def group(self, place: Place, title: str) -> Box:
        """A panel behind the boxes that belong together, named at its top left."""
        b = Box(*place)
        self.groups.append(
            f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="14" fill="{PANEL}" '
            f'stroke="{LINE}" stroke-width="1.2"/>\n'
            f'<text x="{b.x + 16}" y="{b.y + 24}" font-size="14" font-weight="700" '
            f'fill="{NAVY}">{escape(title)}</text>'
        )
        return b

    def caption(self, x: float, y: float, text: str) -> None:
        """A heading over a row of boxes inside a group."""
        self.labels.append(
            f'<text x="{x}" y="{y}" font-size="13" font-weight="700" fill="{MUTED}">'
            f"{escape(text)}</text>"
        )

    def arrow(
        self,
        *points: Point,
        label: str = "",
        at: Point | None = None,
        dashed: bool = False,
        head: bool = True,
    ) -> None:
        """A line through the points, with an arrowhead at the last one unless `head` is off,
        and a label at `at`, or else halfway along its longest stretch."""
        path = " ".join(
            f"{'L' if i else 'M'}{px:.1f} {py:.1f}" for i, (px, py) in enumerate(points)
        )
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        end = ' marker-end="url(#arrow)"' if head else ""
        self.arrows.append(
            f'<path d="{path}" fill="none" stroke="{MUTED}" stroke-width="2"{dash}{end}/>'
        )
        if label:
            if at is None:
                (ax, ay), (bx, by) = max(pairwise(points), key=_length)
                at = ((ax + bx) / 2, (ay + by) / 2)
            self.label(*at, label)

    def fan_out(self, start: Point, y: float, targets: list[Box]) -> None:
        """Arrows from one point to the tops of a row of boxes, along a shared line at y."""
        self.arrow(start, (start[0], y), head=False)
        self.arrow((targets[0].cx, y), (targets[-1].cx, y), head=False)
        for target in targets:
            self.arrow((target.cx, y), target.top())

    def fan_in(self, sources: list[Box], y: float, end: Point) -> None:
        """Arrows from the bottoms of a row of boxes to one point, along a shared line at y."""
        for source in sources:
            self.arrow(source.bottom(), (source.cx, y), head=False)
        self.arrow((sources[0].cx, y), (sources[-1].cx, y), head=False)
        self.arrow((end[0], y), end)

    def label(self, x: float, y: float, *lines: str) -> None:
        """Words on a line, on a white pill so the line doesn't run through them."""
        width = max(len(line) for line in lines) * 6.6 + 16
        height = 18 * len(lines) + 6
        top = y - height / 2
        parts = [
            f'<rect x="{x - width / 2:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height}" '
            f'rx="9" fill="#ffffff" stroke="{PANEL}" stroke-width="1"/>'
        ]
        parts += [
            f'<text x="{x:.1f}" y="{top + 17 + 18 * i:.1f}" text-anchor="middle" '
            f'font-size="{LABEL_SIZE}" fill="{MUTED}">{escape(line)}</text>'
            for i, line in enumerate(lines)
        ]
        self.labels.append("\n".join(parts))

    def note(self, x: float, y: float, *lines: str) -> None:
        """Small words beside the drawing."""
        self.labels.extend(
            f'<text x="{x}" y="{y + 17 * i}" font-size="{LABEL_SIZE}" fill="{MUTED}">'
            f"{escape(line)}</text>"
            for i, line in enumerate(lines)
        )

    def svg(self) -> str:
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img" '
            f'aria-labelledby="title desc" font-family="{FONT}">',
            f'<title id="title">{escape(self.title)}</title>',
            f'<desc id="desc">{escape(self.subtitle)}</desc>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z" fill="{MUTED}"/></marker></defs>',
            f'<rect width="{self.width}" height="{self.height}" fill="{PAPER}"/>',
            f'<text x="40" y="52" font-size="26" font-weight="800" fill="{NAVY}">'
            f"{escape(self.title)}</text>",
            f'<text x="40" y="78" font-size="14" fill="{INK}">{escape(self.subtitle)}</text>',
        ]
        body = self.groups + self.arrows + self.boxes + self.labels
        return "\n".join([*head, *body, "</svg>"]) + "\n"


# --- docs/architecture.md ------------------------------------------------------------------


def cascade() -> Diagram:
    d = Diagram(
        "cascade",
        (1000, 690),
        "Each field's cascade",
        "A field stops at the first step that's sure. With no answer at all, it's not found;"
        " nothing is guessed.",
    )
    rules = d.box(
        (40, 110, 560, 80),
        "1. Rules",
        "places on the page that agree, structured data, postcodes",
        accent="green",
        align="start",
    )
    jev = d.box(
        (40, 232, 560, 80),
        "2. Jev, a typed pick",
        "among the rules' own candidates, with a probability for each",
        accent="cyan",
        align="start",
    )
    gemini = d.box(
        (40, 354, 560, 80),
        "3. Gemini, a quoted reading",
        "or a second opinion; what it reads must be on the page",
        accent="purple",
        align="start",
    )
    investigator = d.box(
        (40, 476, 560, 80),
        "4. Investigator, a web search",
        "for what the pages never say; its answer must cite its pages",
        accent="orange",
        align="start",
    )
    review = d.box((40, 598, 560, 60), "needs_review, with the best answer kept", kind="warn")
    ok = d.box(
        (720, 110, 240, 446),
        "ok",
        "the value, its confidence,",
        "its source and the evidence,",
        "and every step that ran",
        kind="good",
    )
    ladder = (rules, jev, gemini, investigator)
    for step, word in zip(ladder, ("sure", "sure", "sure", "found"), strict=True):
        d.arrow(step.right(), (ok.x, step.cy), label=word)
    for upper, lower in pairwise((*ladder, review)):
        middle = (upper.y + upper.h + lower.y) / 2
        d.arrow(upper.bottom(), lower.top(), label="not sure", at=(upper.cx + 70, middle))
    return d


def pipeline() -> Diagram:
    d = Diagram(
        "pipeline",
        (1160, 850),
        "The pipeline, for one site",
        "Everything before the field specialists runs without a model; a specialist asks one"
        " only when the rules aren't sure.",
    )
    url = d.box((430, 100, 300, 52), "A website address", kind="start")
    fetch = d.box(
        (340, 190, 480, 112),
        "Fetch",
        "the homepage, in a browser, with a screenshot;",
        "the contact page when the homepage lacks a phone,",
        "a general email or a street address;",
        "the privacy policy when no page gives a street address",
    )
    unreadable = d.box(
        (860, 196, 260, 100),
        "A page that can't be read",
        "like one behind a bot check:",
        "each field from what Wikidata",
        "knows, or else an error",
        kind="warn",
    )
    evidence = d.box(
        (300, 350, 560, 140),
        "Evidence, with no model",
        "structured data, title and meta tags, icons; logo candidates",
        "with their places on the screenshot; text by region;",
        "phones, emails, postcodes, links, country clues;",
        "the contact and privacy pages' details;",
        "and what Wikidata knows about the business",
    )
    d.arrow(url.bottom(), fetch.top())
    d.arrow(fetch.right(), unreadable.left())
    d.arrow(fetch.bottom(), evidence.top())
    specialists = []
    for i, field in enumerate(("Name", "Logo", "MCC", "Address", "Phone", "Email", "Social links")):
        lines = ("and coordinates",) if field == "Address" else ()
        specialists.append(d.box((40 + 156 * i, 580, 144, 64), field, *lines))
    d.fan_out(evidence.bottom(), 540, specialists)
    result = d.box(
        (300, 720, 560, 92),
        "SiteResult",
        "per field: the value, its status, confidence and source,",
        "the evidence behind it, and every step with its cost",
        kind="start",
    )
    d.fan_in(specialists, 680, result.top())
    d.label(evidence.cx, 515, "all seven at the same time; their questions for Jev share one call")
    return d


def website_flow() -> Diagram:
    d = Diagram(
        "website-flow",
        (1120, 840),
        "How a website request flows (the demo, later)",
        "The terminal app needs none of this; the demo website runs the same pipeline in"
        " workers, with users' own keys.",
    )
    web = d.box((40, 130, 230, 76), "Website", "React", kind="later")
    api = d.box((370, 130, 260, 76), "API", "FastAPI, REST, OpenAPI")
    db = d.store(
        (780, 112, 300, 112),
        "Postgres",
        "users, encrypted keys, jobs, results,",
        "evidence, images, LLM-call log",
    )
    redis = d.box((370, 330, 260, 86), "Redis", "queue, rate limits,", "cache, progress")
    worker = d.box((370, 520, 260, 76), "Worker", "the pipeline and a browser")
    providers = d.box(
        (150, 690, 700, 90),
        "Model and search providers",
        "Gemini, OpenAI, Anthropic, Jev, SerpAPI: the user's own keys,"
        " or the project's key for free tries",
        "Nominatim: keyless, shared by all users",
    )
    d.arrow(web.right(), api.left(), label="requests")
    d.arrow(api.right(), (db.x, api.cy), label="reads and writes")
    d.arrow(api.bottom(-60), (api.cx - 60, redis.y), label="enqueue", at=(api.cx - 60, 268))
    d.arrow(
        (api.cx + 60, redis.y),
        api.bottom(60),
        label="progress (server-sent events)",
        at=(api.cx + 150, 268),
    )
    d.arrow(redis.bottom(-60), (redis.cx - 60, worker.y), label="jobs", at=(redis.cx - 60, 468))
    d.arrow(
        (redis.cx + 60, worker.y),
        redis.bottom(60),
        label="progress",
        at=(redis.cx + 110, 468),
    )
    d.arrow(
        worker.right(),
        (db.cx, worker.cy),
        (db.cx, db.y + db.h),
        label="results, evidence, images, LLM-call log",
        at=(db.cx, 440),
    )
    d.arrow(worker.bottom(), (worker.cx, providers.y), label="one job's calls")
    return d


# --- docs/plans/accuracy.md ----------------------------------------------------------------


def accuracy_flow() -> Diagram:
    d = Diagram(
        "accuracy-flow",
        (1020, 740),
        "Accurate answers: from free rules to AI to a person",
        "An answer the rules are sure of is kept; 1 in 20 of those is checked anyway, to catch"
        " rules that start to slip.",
    )
    site = d.box((380, 100, 260, 52), "A website address", kind="start")
    rules = d.box((360, 196, 300, 70), "Free rules", "no AI, no tokens", accent="green")
    kept = d.box((60, 330, 230, 60), "Kept", kind="good")
    ai = d.box(
        (660, 318, 320, 84),
        "AI pass",
        "sees only the evidence",
        "for that one answer",
        accent="cyan",
    )
    check = d.box((400, 470, 220, 60), "LLM check", accent="purple")
    person = d.box((720, 464, 260, 74), "A person looks it up", "and fills it in", kind="warn")
    final = d.box((390, 650, 240, 56), "Final answer", kind="start")
    d.arrow(site.bottom(), rules.top())
    d.arrow(rules.left(), (kept.cx, rules.cy), kept.top(), label="sure", at=(260, rules.cy))
    d.arrow(
        rules.right(),
        (ai.cx, rules.cy),
        ai.top(),
        label="unsure, or nothing found",
        at=(ai.cx, 274),
    )
    d.arrow(ai.left(), (check.cx, ai.cy), check.top(), label="answered", at=(585, ai.cy))
    d.arrow(ai.bottom(30), (ai.cx + 30, person.y), label="still missing")
    d.arrow(
        kept.bottom(30),
        (kept.cx + 30, check.cy),
        check.left(),
        label="1 in 20, at random",
        at=(300, check.cy),
    )
    d.arrow(kept.bottom(-40), (kept.cx - 40, final.cy), final.left())
    d.arrow(check.bottom(), final.top(), label="agrees")
    d.arrow(check.right(), (person.x, check.cy), label="disagrees")
    d.arrow(person.bottom(), (person.cx, final.cy), final.right())
    return d


def measurement_loop() -> Diagram:
    d = Diagram(
        "measurement-loop",
        (960, 440),
        "How a change is measured",
        "Every run sees the same saved pages, so only the rules change; the test set is never"
        " used while writing them.",
    )
    change = d.box((40, 150, 210, 70), "Change a rule")
    run = d.box(
        (300, 136, 290, 98),
        "Run v2 on saved copies",
        "of the tuning sites' pages,",
        "offline and free",
    )
    compare = d.box(
        (640, 136, 280, 98),
        "Compare with the last run",
        "what got better,",
        "what got worse",
    )
    keep = d.box((670, 320, 220, 60), "Keep the change", kind="good")
    test = d.box(
        (330, 304, 290, 92),
        "Run the test set",
        "from time to time: sites never",
        "used while writing rules",
    )
    score = d.box((40, 318, 230, 64), "The accuracy we report", kind="start")
    d.arrow(change.right(), run.left())
    d.arrow(run.right(), compare.left())
    d.arrow(
        compare.top(),
        (compare.cx, 112),
        (change.cx, 112),
        change.top(),
        label="something got worse",
        at=(470, 112),
    )
    d.arrow(compare.bottom(), keep.top(), label="only better")
    d.arrow(keep.left(), test.right())
    d.arrow(test.left(), score.right())
    return d


# --- docs/codebase.md ----------------------------------------------------------------------


def layers() -> Diagram:
    d = Diagram(
        "layers",
        (1000, 600),
        "The layers, and the rules between them",
        "Each arrow points to what a layer may import. import-linter checks the rules in CI, so a"
        " change that breaks one fails.",
    )
    entry = d.box(
        (250, 110, 500, 80),
        "Entry points: cli, mcp, evaluation, wiring",
        "build a RunContext from real parts, and call the pipeline",
        kind="start",
    )
    logic = d.box(
        (40, 280, 380, 110),
        "Logic",
        "pipeline, resolvers, agent, evidence",
        "no I/O libraries: it reaches out through ports",
        accent="cyan",
    )
    infra = d.box(
        (580, 280, 380, 110),
        "Infrastructure",
        "fetch, llm, decide, retrieval, services, adapters",
        "implements the ports, and does the I/O",
        accent="purple",
    )
    core = d.box(
        (250, 470, 500, 90),
        "core",
        "models, ports, errors, settings, pure helpers",
        "imports nothing else from bi2, and no I/O libraries",
        accent="green",
    )
    d.arrow(entry.bottom(-120), (entry.cx - 120, 240), (logic.cx, 240), logic.top())
    d.arrow(entry.bottom(120), (entry.cx + 120, 240), (infra.cx, 240), infra.top())
    d.arrow(logic.bottom(), (logic.cx, 430), (core.cx - 120, 430), core.top(-120))
    d.arrow(infra.bottom(), (infra.cx, 430), (core.cx + 120, 430), core.top(120))
    d.arrow(logic.right(), infra.left(), dashed=True, head=False)
    d.label(500, logic.cy, "never import", "each other")
    return d


# --- docs/reviews/2026-10-12.md ------------------------------------------------------------


def review_parts() -> Diagram:
    d = Diagram(
        "review-parts",
        (1300, 780),
        "How the parts fit together",
        "As it stood on 2026-10-12: the part that works out the answers reaches the outside world"
        " only through plugs.",
    )
    d.group((40, 100, 230, 270), "How people use it")
    app = d.box((60, 140, 190, 80), "Terminal app", "analyze sites,", "check results")
    web = d.box((60, 250, 190, 80), "Website demo", "(later)", kind="later")
    setup = d.box(
        (320, 125, 220, 110),
        "Sets up each run",
        "plugs in the real browser,",
        "the downloader and storage",
    )
    think = d.group((590, 100, 440, 280), "Works out the answers")
    one = d.box((610, 148, 400, 64), "Runs one site", "from start to finish")
    collect = d.box((610, 250, 190, 90), "Collects evidence", "from the page")
    decide = d.box((820, 250, 190, 90), "Decides each field", "and how sure it is")
    d.group((1060, 100, 200, 280), "Shared building blocks")
    shapes = d.box(
        (1075, 160, 170, 160),
        "Data shapes",
        "every piece of data's",
        "shape, and the rules",
        "it must follow",
    )
    outside = d.group((310, 440, 700, 190), "Talks to the outside world")
    browser = d.box((330, 482, 200, 90), "A real browser", "loads and reads pages")
    download = d.box((560, 482, 200, 90), "A downloader", "fetches logo files", "safely")
    save = d.box((790, 482, 200, 90), "Storage", "keeps results", "and files")
    sites = d.store((330, 670, 430, 70), "Business websites")
    folder = d.store((790, 670, 200, 70), "Results folder")
    d.arrow(app.right(), setup.left())
    d.arrow(web.right(), (285, web.cy), (285, setup.cy + 35), setup.left(35), dashed=True)
    d.arrow(setup.right(), one.left())
    d.arrow((collect.cx, one.y + one.h), collect.top())
    d.arrow((decide.cx, one.y + one.h), decide.top())
    d.arrow(decide.right(), (shapes.x, decide.cy))
    d.arrow(collect.bottom(), (collect.cx, 362), (shapes.cx, 362), shapes.bottom())
    d.arrow(setup.bottom(), browser.top())
    d.arrow((setup.cx, 412), (save.cx, 412), head=False)
    d.arrow((download.cx, 412), download.top())
    d.arrow((save.cx, 412), save.top())
    d.arrow((980, think.y + think.h), (980, outside.y), dashed=True, label="only through plugs")
    for source, kept in ((browser, sites), (download, sites), (save, folder)):
        d.arrow(source.bottom(), (source.cx, kept.y))
    return d


def review_layers() -> Diagram:
    d = Diagram(
        "review-layers",
        (960, 560),
        "The layers",
        "Each layer may use the ones below it, never the ones beside or above it.",
    )
    entry = d.box(
        (260, 110, 440, 76),
        "Commands people run",
        "and the setup for each run",
        kind="start",
    )
    logic = d.box(
        (60, 260, 380, 96),
        "Working out the answers",
        "collecting evidence, deciding fields",
        accent="cyan",
    )
    infra = d.box(
        (520, 260, 380, 96),
        "Talking to the outside world",
        "browser, downloads, storage;",
        "later AI models and search",
        accent="purple",
    )
    core = d.box(
        (260, 430, 440, 92),
        "Shared building blocks",
        "data shapes, rules, settings, plugs",
        accent="green",
    )
    d.arrow(entry.bottom(-110), (entry.cx - 110, 222), (logic.cx, 222), logic.top())
    d.arrow(entry.bottom(110), (entry.cx + 110, 222), (infra.cx, 222), infra.top())
    d.arrow(logic.bottom(), (logic.cx, 394), (core.cx - 110, 394), core.top(-110))
    d.arrow(infra.bottom(), (infra.cx, 394), (core.cx + 110, 394), core.top(110))
    return d


def review_analyze() -> Diagram:
    d = Diagram(
        "review-analyze",
        (1120, 1000),
        "What happens when you analyze a site",
        "As it stood on 2026-10-12, before the MCC and the address were built.",
    )
    url = d.box((430, 100, 240, 52), "A website address", kind="start")
    load = d.box((410, 190, 280, 56), "Load the page in a real browser")
    snapshot = d.box(
        (330, 300, 440, 92),
        "What the browser captured",
        "the page, its images and where they sit,",
        "its text by area, a screenshot",
    )
    failed = d.box(
        (820, 300, 260, 92),
        "A failed result",
        "every field is an error,",
        "with the reason",
        kind="bad",
    )
    collect = d.box((410, 440, 280, 56), "Collect the evidence", "no AI")
    d.arrow(url.bottom(), load.top())
    d.arrow(load.bottom(), snapshot.top(), label="loaded")
    d.arrow(
        load.right(),
        (failed.cx, load.cy),
        failed.top(),
        label="couldn't load",
        at=(820, load.cy),
    )
    d.arrow(snapshot.bottom(), collect.top())
    fields = [
        d.box((40 + 212 * i, 560, 196, 64), f"Decide the {name}")
        for i, name in enumerate(("name", "logo", "phone", "social links"))
    ]
    fields.append(d.box((888, 560, 196, 64), "MCC and address", "not built yet", kind="later"))
    d.fan_out(collect.bottom(), 530, fields)
    result = d.box(
        (330, 690, 440, 92),
        "One result for the site",
        "each field with its answer, status,",
        "confidence and reasons",
        kind="start",
    )
    d.fan_in(fields, 656, result.top())
    outputs = [
        d.box((110, 830, 260, 64), "A results file", "for scoring"),
        d.box((420, 830, 260, 64), "A folder per site", "result, evidence, screenshot, logo"),
        d.box((730, 830, 260, 64), "The report page", "the answers beside the evidence"),
    ]
    d.fan_out(result.bottom(), 806, outputs)
    score = d.box((110, 926, 260, 52), "Score against the gold set", kind="good")
    d.arrow(outputs[0].bottom(), score.top())
    return d


def review_loading() -> Diagram:
    d = Diagram(
        "review-loading",
        (970, 1090),
        "Loading a page",
        "The fast browser first; a full browser only when a site refuses it.",
    )
    url = d.box((250, 100, 240, 52), "A website address", kind="start")
    public = d.ask((210, 190, 320, 60), "On the public internet?")
    refused = d.box((630, 194, 260, 52), "Refused, for safety", kind="bad")
    fast = d.box((220, 296, 300, 56), "Load it in the fast browser")
    wait = d.box(
        (190, 390, 360, 70),
        "Wait for the page to load,",
        "then for its network activity to settle",
    )
    bot_check = d.ask(
        (190, 500, 360, 84),
        "Is a bot check running?",
        "an error page with scripts,",
        "or a known check page",
    )
    give = d.box((630, 512, 280, 60), "Give it up to 10 seconds", "to pass")
    scroll = d.box(
        (190, 630, 360, 70),
        "Scroll to the bottom and back,",
        "reading the text at the bottom too",
    )
    read = d.box((190, 740, 360, 64), "Read everything in one go,", "and take the screenshot")
    refusal = d.ask(
        (190, 850, 360, 84),
        "Did the site refuse?",
        "still a check page, an error,",
        "or a dropped connection",
    )
    full = d.box(
        (620, 857, 310, 70),
        "Load it again in a full browser",
        "Chromium, else Chrome, else Edge",
    )
    done = d.box((250, 1000, 240, 56), "What the browser captured", kind="good")
    d.arrow(url.bottom(), public.top())
    d.arrow(public.right(), refused.left(), label="no")
    d.arrow(public.bottom(), fast.top(), label="yes")
    d.arrow(fast.bottom(), wait.top())
    d.arrow(wait.bottom(), bot_check.top())
    d.arrow(bot_check.right(), give.left(), label="yes")
    d.arrow(bot_check.bottom(), scroll.top(), label="no")
    d.arrow(give.bottom(), (give.cx, scroll.cy), scroll.right())
    d.arrow(scroll.bottom(), read.top())
    d.arrow(read.bottom(), refusal.top())
    d.arrow(refusal.bottom(), done.top(), label="no")
    d.arrow(refusal.right(), full.left(), label="yes")
    d.arrow(full.bottom(), (full.cx, done.cy), done.right())
    return d


def review_evidence() -> Diagram:
    d = Diagram(
        "review-evidence",
        (1240, 690),
        "Evidence: everything collected before any AI",
        "Read once from what the browser captured; the field specialists, and later the models,"
        " only ever see this.",
    )
    capture = d.box(
        (40, 300, 250, 90),
        "What the browser captured",
        "the page, its images,",
        "its text, a screenshot",
        kind="start",
    )
    evidence = d.group((340, 100, 860, 550), "The evidence")
    d.arrow(capture.right(), (evidence.x, capture.cy))
    d.caption(360, 156, "Read from the page's code")
    from_code = (
        ("Tags", "title, site name,", "sharing tags"),
        ("Structured data", "name, logo, phone,", "address, profiles"),
        ("Language", "of the page"),
        ("Links", "social profiles,", "contact pages"),
        ("Platform page", "the business's name", "there, its website"),
    )
    for i, (title, *lines) in enumerate(from_code):
        d.box((360 + 166 * i, 168, 154, 86), title, *lines)
    d.caption(360, 286, "Read from the visible text")
    text = d.box((360, 298, 320, 70), "Text by area", "header, main content, footer")
    postcodes = d.box((730, 298, 260, 70), "Postcodes", "provinces and states")
    d.arrow(text.right(), postcodes.left())
    d.caption(360, 400, "Read from the images")
    d.box((360, 412, 400, 70), "Logo candidates", "every image the page drew, ranked and numbered")
    d.caption(360, 514, "Worked out from those")
    guess = d.box(
        (360, 526, 270, 100),
        "First guess at the country",
        "from the structured data,",
        "the postcodes and the language",
    )
    contacts = d.box(
        (680, 526, 270, 100),
        "Contacts",
        "phones read for that country,",
        "where each was found, emails,",
        "the copyright line",
    )
    countries = d.box(
        (1000, 526, 180, 100),
        "Countries again",
        "with the phones'",
        "area codes as clues",
    )
    d.arrow(guess.right(), contacts.left())
    d.arrow(contacts.right(), countries.left())
    return d


def review_cascade() -> Diagram:
    d = Diagram(
        "review-cascade",
        (980, 630),
        "Turning evidence into answers",
        "Every field runs the same loop over its ways of finding the answer.",
    )
    attempt = d.box(
        (350, 100, 420, 80),
        "Try the next way of finding the answer",
        "today: the page itself; later: AI models and search",
    )
    got = d.ask((440, 230, 240, 60), "Got an answer?")
    accepted = d.box((40, 230, 230, 60), "Accepted", kind="good")
    keep = d.box((40, 350, 230, 60), "Keep the surest so far")
    more = d.ask((420, 350, 280, 60), "Any ways left to try?")
    review = d.box(
        (40, 520, 290, 76),
        "Needs review",
        "the best answer goes to an analyst",
        kind="warn",
    )
    missing = d.box((370, 520, 260, 76), "Not found", "nothing is guessed")
    error = d.box((670, 520, 260, 76), "Error", "each failure is recorded", kind="bad")
    d.arrow(attempt.bottom(), got.top())
    d.arrow(got.left(), accepted.right(), label="yes, and sure enough")
    d.arrow(
        got.bottom(-60),
        (got.cx - 60, 320),
        (keep.cx, 320),
        keep.top(),
        label="yes, but not sure enough",
        at=(330, 320),
    )
    d.arrow(got.bottom(60), (got.cx + 60, more.y), label="no, or it failed")
    d.arrow(keep.right(), more.left())
    d.arrow(more.right(), (820, more.cy), (820, attempt.cy), attempt.right(), label="yes")
    d.arrow(
        more.bottom(-120),
        (more.cx - 120, 460),
        (review.cx, 460),
        review.top(),
        label="no, but one was kept",
        at=(300, 460),
    )
    d.arrow(
        more.bottom(-60),
        (more.cx - 60, missing.y),
        label="no answer at all",
        at=(more.cx - 60, 485),
    )
    d.arrow(
        more.bottom(120),
        (more.cx + 120, 460),
        (error.cx, 460),
        error.top(),
        label="every way failed",
        at=(error.cx, 490),
    )
    return d


def review_logo() -> Diagram:
    d = Diagram(
        "review-logo",
        (1080, 1170),
        "The logo, step by step",
        "As it stood on 2026-10-12, before Jev and Gemini joined: the rules' ranking does the work.",
    )
    ranked = d.box((330, 100, 360, 56), "Images ranked by how logo-like they are", kind="start")
    first = d.ask(
        (280, 200, 460, 84),
        "Is the top one drawn in the page,",
        "with no file of its own, while",
        "the page names a logo file?",
    )
    named = d.box((110, 330, 270, 56), "Try the named logo file first")
    top = d.box((640, 330, 270, 56), "Try the top image")
    has_file = d.ask((380, 440, 260, 60), "Does it have a file?")
    download = d.box(
        (90, 570, 350, 84),
        "Download it safely",
        "public addresses only, redirects checked,",
        "at most 5 MB",
    )
    cut = d.box((600, 584, 300, 56), "Cut it out of the screenshot")
    look = d.box(
        (310, 710, 400, 70),
        "Look at the bytes",
        "what kind of image it really is, and its size",
    )
    shape = d.ask((370, 830, 280, 56), "A logo's shape and size?")
    retry = d.box(
        (740, 816, 280, 84),
        "Try the next image, up to 3,",
        "each one lowering",
        "the confidence",
        kind="warn",
    )
    save = d.box((370, 950, 280, 56), "Save it with its real file type")
    logo = d.box(
        (310, 1060, 400, 70),
        "The logo",
        "its address, the saved file, and the site's app icon",
        kind="good",
    )
    d.arrow(ranked.bottom(), first.top())
    d.arrow(first.left(), (named.cx, first.cy), named.top(), label="yes", at=(named.cx, 300))
    d.arrow(first.right(), (top.cx, first.cy), top.top(), label="no", at=(top.cx, 300))
    d.arrow(named.bottom(), (named.cx, 414), (has_file.cx - 40, 414), has_file.top(-40))
    d.arrow(top.bottom(), (top.cx, 414), (has_file.cx + 40, 414), has_file.top(40))
    d.arrow(
        has_file.bottom(-60),
        (has_file.cx - 60, 535),
        (download.cx, 535),
        download.top(),
        label="yes",
        at=(357, 535),
    )
    d.arrow(
        has_file.bottom(60),
        (has_file.cx + 60, 535),
        (cut.cx, 535),
        cut.top(),
        label="no",
        at=(660, 535),
    )
    d.arrow(download.bottom(), (download.cx, 684), (look.cx - 80, 684), look.top(-80))
    d.arrow(cut.bottom(), (cut.cx, 684), (look.cx + 80, 684), look.top(80))
    d.arrow(look.bottom(), shape.top())
    d.arrow(shape.right(), retry.left(), label="no")
    d.note(
        retry.x,
        922,
        "no: not an image, a tracking pixel,",
        "under 16 pixels, a long strip,",
        "or photo-sized",
    )
    d.arrow(retry.right(), (1050, retry.cy), (1050, has_file.cy), has_file.right())
    d.arrow(shape.bottom(), save.top(), label="yes")
    d.arrow(save.bottom(), logo.top())
    return d


def review_knowing() -> Diagram:
    d = Diagram(
        "review-knowing",
        (1100, 650),
        "How we know an answer is right",
        "While analyzing, v2 can only say how sure it is; afterwards, checked answers say whether"
        " it was right.",
    )
    d.group((40, 122, 1000, 176), "While analyzing: the truth isn't known")
    evidence = d.box((60, 172, 220, 76), "Evidence from the page")
    sure = d.box(
        (330, 162, 340, 96),
        "How sure v2 is",
        "from how many independent places",
        "agree, and how clearly",
    )
    status = d.box((720, 172, 280, 76), "Accepted, or sent to review")
    d.group((40, 350, 1000, 270), "Afterwards: was it right?")
    gold = d.box((60, 400, 260, 76), "Gold-set answers", "confirmed by a person")
    eye = d.box((60, 510, 260, 76), "The report page", "look at each logo")
    compare = d.box((380, 461, 240, 64), "Compare every answer")
    accuracy = d.box(
        (680, 445, 320, 96),
        "Accuracy",
        "and how often an accepted",
        "answer was wrong",
        kind="good",
    )
    d.arrow(evidence.right(), sure.left())
    d.arrow(sure.right(), status.left())
    d.arrow(status.bottom(), (status.cx, 324), (compare.cx, 324), compare.top())
    d.arrow(gold.right(), (350, gold.cy), (350, compare.cy - 12), compare.left(-12))
    d.arrow(eye.right(), (350, eye.cy), (350, compare.cy + 12), compare.left(12))
    d.arrow(compare.right(), accuracy.left())
    d.arrow(
        accuracy.right(),
        (1070, accuracy.cy),
        (1070, 102),
        (sure.cx, 102),
        sure.top(),
        label="tune the weights and the threshold",
        at=(785, 102),
    )
    return d


def review_result() -> Diagram:
    d = Diagram(
        "review-result",
        (1260, 350),
        "What a result contains",
        "From what the browser captured, to the evidence, to one entry per field.",
    )
    capture = d.box(
        (40, 140, 300, 140),
        "What the browser captured",
        "the page as drawn, every image",
        "and where it sits, the text",
        "by area, a screenshot",
    )
    evidence = d.box(
        (390, 140, 290, 140),
        "The evidence",
        "names, structured data,",
        "contacts, countries, links,",
        "ranked logo candidates",
    )
    result = d.box(
        (730, 160, 180, 100),
        "The result",
        "for the site:",
        "one entry per field",
        kind="start",
    )
    field = d.box(
        (960, 100, 260, 220),
        "Each field has",
        "• the answer",
        "• a status: ok, needs review,",
        f"{INDENT}not found or error",
        "• a confidence from 0 to 1",
        "• where it came from",
        "• the quotes or links behind it",
        "• every step tried, and why",
        kind="good",
        align="start",
    )
    d.arrow(capture.right(), evidence.left())
    d.arrow(evidence.right(), result.left())
    d.arrow(result.right(), field.left())
    return d


def review_measuring() -> Diagram:
    d = Diagram(
        "review-measuring",
        (1420, 470),
        "Measuring it",
        "Each gold site is loaded once and its pages saved, so every later run is offline, free"
        " and the same.",
    )
    gold = d.box(
        (40, 200, 250, 92),
        "The gold set",
        "56 sites with answers",
        "a person confirmed",
        kind="start",
    )
    load = d.box((330, 200, 250, 92), "Load each site once,", "and save the pages")
    saved = d.store((620, 206, 170, 80), "Saved pages")
    coverage = d.box(
        (840, 110, 290, 92),
        "Coverage",
        "is the right answer somewhere",
        "in the evidence?",
    )
    analysis = d.box((840, 300, 290, 80), "Analysis", "the final answers")
    coverage_page = d.box((1180, 126, 200, 60), "Report page")
    accuracy = d.box(
        (1180, 260, 200, 80),
        "Accuracy",
        "how many answers",
        "match the gold set",
        kind="good",
    )
    answers_page = d.box((1180, 370, 200, 70), "Report page", "with the answers")
    d.arrow(gold.right(), load.left())
    d.arrow(load.right(), saved.left())
    d.arrow(saved.right(-14), (815, saved.cy - 14), (815, coverage.cy), coverage.left())
    d.arrow(saved.right(14), (815, saved.cy + 14), (815, analysis.cy), analysis.left())
    d.arrow(coverage.right(), coverage_page.left())
    d.arrow(
        analysis.right(-14),
        (1155, analysis.cy - 14),
        (1155, accuracy.cy),
        accuracy.left(),
    )
    d.arrow(
        analysis.right(14),
        (1155, analysis.cy + 14),
        (1155, answers_page.cy),
        answers_page.left(),
    )
    return d


DIAGRAMS = (
    cascade,
    pipeline,
    website_flow,
    accuracy_flow,
    measurement_loop,
    layers,
    review_parts,
    review_layers,
    review_analyze,
    review_loading,
    review_evidence,
    review_cascade,
    review_logo,
    review_knowing,
    review_result,
    review_measuring,
)

if __name__ == "__main__":
    here = Path(__file__).parent
    for draw in DIAGRAMS:
        diagram = draw()
        (here / f"{diagram.name}.svg").write_text(diagram.svg(), encoding="utf-8", newline="\n")
