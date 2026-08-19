"""Assemble the lightweight web-gym client into an output directory.

The scoring engine and matter internals live in the separate Cloudflare Worker.
The public site contains only static interface assets.

Markdown posts in ``docs/posts/*.md`` are rendered to static HTML alongside the
gym: ``dist/posts/<slug>.html`` plus an index at ``dist/posts/index.html``.

    python web/build_site.py dist
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    import markdown
    from markdown.preprocessors import Preprocessor
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the environment
    raise SystemExit(
        "web/build_site.py needs the 'markdown' package "
        '(pip install markdown, or pip install -e ".[dev]")'
    ) from exc

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
POSTS_SRC = ROOT / "docs" / "posts"
POST_ASSETS_SRC = POSTS_SRC / "assets"

SITE_URL = "https://jamesbaker1.github.io/playbook/"
OG_IMAGE = SITE_URL + "og-card.png"
REPO_URL = "https://github.com/jamesbaker1/playbook"
DEFAULT_AUTHOR = "James Baker"

MARKDOWN_EXTENSIONS = ["tables", "fenced_code", "smarty"]

# Math spans, in the two delimiter styles the post template hands to KaTeX.
#
# Backtick code spans are matched first and passed through untouched, so prose
# that *mentions* a delimiter (``use `$$` for display math``) is not mistaken for
# math. A span may wrap across a line but never across a blank one, so a stray
# unpaired delimiter swallows at most its own paragraph rather than the rest of
# the document.
_MATH_BODY = r"(?:[^\n]|\n(?!\s*\n))+?"
MATH_SPAN_RE = re.compile(
    r"(?P<code>`+[^`]*?`+)"
    rf"|(?P<display>\$\${_MATH_BODY}\$\$)"
    rf"|(?P<inline>\\\({_MATH_BODY}\\\))"
)

# Runs after the fenced-code preprocessor (priority 25), so fenced blocks have
# already been stashed and their contents are invisible here.
MATH_PREPROCESSOR_PRIORITY = 24


class MathStashPreprocessor(Preprocessor):
    """Hold math spans out of markdown's inline processing.

    Markdown treats ``(`` and ``)`` as escapable, so ``\\(x\\)`` would otherwise
    reach the page as a bare ``(x)`` with the delimiters KaTeX needs stripped
    out; ``_`` and ``*`` inside ``$$...$$`` would likewise be eaten as emphasis.
    Stashing each span verbatim keeps the delimiters intact for the client-side
    renderer. Content is HTML-escaped so a ``<`` in a formula stays text.
    """

    def run(self, lines: list[str]) -> list[str]:
        def stash(match: re.Match[str]) -> str:
            if match.lastgroup == "code":
                return match.group(0)
            return self.md.htmlStash.store(html.escape(match.group(0), quote=False))

        return MATH_SPAN_RE.sub(stash, "\n".join(lines)).split("\n")


def make_renderer() -> markdown.Markdown:
    """The markdown renderer every post is built with."""
    renderer = markdown.Markdown(extensions=MARKDOWN_EXTENSIONS)
    renderer.preprocessors.register(
        MathStashPreprocessor(renderer), "katex-math", MATH_PREPROCESSOR_PRIORITY
    )
    return renderer

ASSETS = [
    "index.html",
    "style.css",
    "posts.css",
    "api-base.js",
    "citation.js",
    "score.js",
    "capture.js",
    "draft-store.js",
    "app.js",
    "contribute.js",
    "policy.json",
    "favicon.svg",
    "og-card.png",
]


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    date: dt.date
    description: str
    author: str
    body_html: str
    canonical: str | None = None

    @property
    def href(self) -> str:
        return f"{self.slug}.html"

    @property
    def self_url(self) -> str:
        return f"{SITE_URL}posts/{self.href}"

    @property
    def url(self) -> str:
        """Where the post canonically lives — its own page unless it says otherwise.

        A post first published elsewhere declares that home in ``canonical:``; the
        page built here then points search engines and shares at it. Only the
        canonical link and ``og:url`` follow the declaration: the page still
        renders in full, and the writing index still links the local copy.
        """
        return self.canonical or self.self_url

    @property
    def date_display(self) -> str:
        return self.date.strftime("%d %B %Y").lstrip("0")

    @property
    def date_iso(self) -> str:
        return self.date.isoformat()


def _coerce_date(value: object, source: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{source}: 'date' must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError(f"{source}: 'date' must be an ISO date (YYYY-MM-DD)")


def parse_post(path: Path, renderer: markdown.Markdown) -> Post:
    """Split ``path`` into YAML front matter and rendered markdown body."""
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: post must open with '---' YAML front matter")

    _, front_matter, body = raw.split("---", 2)
    meta = yaml.safe_load(front_matter)
    if not isinstance(meta, dict):
        # Empty or malformed front matter falls through to the required-key check.
        meta = {}

    for key in ("title", "date", "description"):
        if not str(meta.get(key, "")).strip():
            raise ValueError(f"{path.name}: front matter is missing required key '{key}'")

    canonical = str(meta.get("canonical") or "").strip() or None
    if canonical and not canonical.startswith(("http://", "https://")):
        raise ValueError(f"{path.name}: 'canonical' must be an absolute URL")

    renderer.reset()
    body_html = renderer.convert(body.strip())
    # Wide tables scroll inside their own box rather than widening the page.
    body_html = body_html.replace("<table>", '<div class="table-scroll"><table>')
    body_html = body_html.replace("</table>", "</table></div>")

    return Post(
        slug=path.stem,
        title=str(meta["title"]).strip(),
        date=_coerce_date(meta["date"], path.name),
        description=str(meta["description"]).strip(),
        author=str(meta.get("author") or DEFAULT_AUTHOR).strip(),
        body_html=body_html,
        canonical=canonical,
    )


def load_posts(posts_dir: Path = POSTS_SRC) -> list[Post]:
    """Every post under ``posts_dir``, newest first. Missing directory means none."""
    if not posts_dir.is_dir():
        return []
    renderer = make_renderer()
    posts = [parse_post(path, renderer) for path in sorted(posts_dir.glob("*.md"))]
    return sorted(posts, key=lambda post: (post.date, post.slug), reverse=True)


# ------------------------------------------------------------------ templates


def _head(*, title: str, description: str, url: str, og_type: str) -> str:
    title_e = html.escape(title)
    description_e = html.escape(description, quote=True)
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_e}</title>
<meta name="description" content="{description_e}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{title_e}">
<meta property="og:description" content="{description_e}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{OG_IMAGE}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="../posts.css">"""


# Post pages only — the gym and the writing index carry no math. Pinned version
# with subresource-integrity hashes verified against the bytes cdn.jsdelivr.net
# actually serves for katex@0.18.4.
KATEX_VERSION = "0.18.4"
KATEX_HEAD = r"""<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.18.4/dist/katex.min.css" integrity="sha384-u1zONI5gPXUx0UKI62c75/zww972y0v2rSK5ZYlVdS6xEuWDeZWUI66v6t1gvlXJ" crossorigin="anonymous">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.18.4/dist/katex.min.js" integrity="sha384-ykMNcWQhhTUb0YV9SPpPUFURHZ+tWmubkakGBP+OgNK/UXdO2gtzglWx0Rj9hnO3" crossorigin="anonymous"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.18.4/dist/contrib/auto-render.min.js" integrity="sha384-bjyGPfbij8/NDKJhSGZNP/khQVgtHUE5exjm4Ydllo42FwIgYsdLO2lXGmRBf5Mz" crossorigin="anonymous" onload="renderMathInElement(document.querySelector('.post-body'), {delimiters: [{left: '$$', right: '$$', display: true}, {left: '\\(', right: '\\)', display: false}], throwOnError: false});"></script>"""


def _chrome_header(tag: str, links: str) -> str:
    return f"""<header>
  <a class="brand" href="../" aria-label="Playbook home"><span class="mark">playbook</span></a>
  <span class="tag">{tag}</span>
  <span class="spacer"></span>
{links}
</header>"""


FOOTER = f"""<footer>
  <span>Synthetic matters only. Notes on building an open gym for legal work.</span>
  <span><a href="../">the gym</a> · <a href="{REPO_URL}">source on github</a></span>
</footer>"""


def render_post_page(post: Post) -> str:
    links = (
        '  <a class="header-link" href="./">all writing</a>\n'
        '  <a class="header-link" href="../">the gym</a>\n'
        f'  <a class="header-link" href="{REPO_URL}#readme">about</a>'
    )
    head = _head(
        title=f"{post.title} — playbook",
        description=post.description,
        url=post.url,
        og_type="article",
    )
    return f"""<!doctype html>
<html lang="en">
<head>
{head}
{KATEX_HEAD}
</head>
<body class="post-page">
{_chrome_header("writing", links)}

<main>
  <article>
    <p class="eyebrow">writing</p>
    <h1>{html.escape(post.title)}</h1>
    <p class="post-meta">
      <time datetime="{post.date_iso}">{post.date_display}</time> · {html.escape(post.author)}
    </p>
    <div class="post-body">
{post.body_html}
    </div>
  </article>
  <p class="post-back"><a href="./">← all writing</a></p>
</main>

{FOOTER}
</body>
</html>
"""


def render_index_page(posts: list[Post]) -> str:
    links = (
        '  <a class="header-link" href="../">the gym</a>\n'
        f'  <a class="header-link" href="{REPO_URL}#readme">about</a>'
    )
    if posts:
        entries = "\n".join(
            f"""    <article>
      <time datetime="{post.date_iso}">{post.date_display}</time>
      <h2><a href="{post.href}">{html.escape(post.title)}</a></h2>
      <p>{html.escape(post.description)}</p>
    </article>"""
            for post in posts
        )
        listing = f'  <div class="post-list">\n{entries}\n  </div>'
    else:
        listing = '  <p class="post-empty">nothing published yet.</p>'

    head = _head(
        title="writing — playbook",
        description="Notes on building an open gym for evaluating and training legal agents.",
        url=f"{SITE_URL}posts/",
        og_type="website",
    )
    return f"""<!doctype html>
<html lang="en">
<head>
{head}
</head>
<body class="post-page">
{_chrome_header("writing", links)}

<main>
  <p class="eyebrow">writing</p>
  <h1>Notes from the gym.</h1>
  <p class="post-intro">Working notes on evaluating and training agents on real legal
  work — what the environment measures, what the models miss, and what changes.</p>
{listing}
</main>

{FOOTER}
</body>
</html>
"""


# ---------------------------------------------------------------------- build


def copy_post_assets(out_dir: Path, posts_dir: Path = POSTS_SRC) -> list[Path]:
    """Mirror ``<posts_dir>/assets`` into ``<out_dir>/posts/assets``.

    Post pages sit at ``posts/<slug>.html``, so a markdown reference to
    ``assets/<name>.svg`` resolves against the copied tree without rewriting.
    Returns the copied files, relative to the asset root.
    """
    source = posts_dir / "assets"
    if not source.is_dir():
        return []
    target = out_dir / "posts" / "assets"
    shutil.copytree(source, target, dirs_exist_ok=True)
    return sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())


def build_posts(out_dir: Path, posts_dir: Path = POSTS_SRC) -> list[Post]:
    posts = load_posts(posts_dir)
    target = out_dir / "posts"
    target.mkdir(parents=True, exist_ok=True)
    for post in posts:
        (target / post.href).write_text(render_post_page(post), encoding="utf-8")
    (target / "index.html").write_text(render_index_page(posts), encoding="utf-8")
    copy_post_assets(out_dir, posts_dir)
    return posts


def build(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in ASSETS:
        shutil.copy2(WEB / name, out_dir / name)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    posts = build_posts(out_dir)
    figures = sorted((out_dir / "posts" / "assets").rglob("*"))

    print(
        f"{out_dir}: {len(ASSETS)} static assets, {len(posts)} posts, "
        f"{sum(1 for path in figures if path.is_file())} post figures"
    )


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "dist"))
