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


DIAGRAMS = (
    cascade,
    pipeline,
    website_flow,
    accuracy_flow,
    measurement_loop,
    layers,
)

if __name__ == "__main__":
    here = Path(__file__).parent
    for draw in DIAGRAMS:
        diagram = draw()
        (here / f"{diagram.name}.svg").write_text(diagram.svg(), encoding="utf-8", newline="\n")
