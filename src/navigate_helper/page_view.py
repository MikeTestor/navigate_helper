"""Page viewer content: a raw Manual Page next to its Cleaned Page.

The rules are in docs/design-decisions.md, section "Stages 4 and 5 – Gradio dev app". Nothing here imports Gradio.
"""

import hashlib
import html
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from navigate_helper.clean import collapse
from navigate_helper.config import Config, load_config

FILE_URL_PREFIX = "/gradio_api/file="
IFRAME_HEIGHT = 560

_EXTERNAL = re.compile(r"^(https?:|mailto:|data:|//)", re.IGNORECASE)
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n\n?", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[\]\(([^)]*)\)")
_MD_PAGE_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(<[^>]*>\)")
_view_dir: Path | None = None


@dataclass(frozen=True)
class PageView:
    """What the Page viewer shows: an HTML heading, the raw page iframe, and the Cleaned Page as Markdown."""

    heading: str
    raw_html: str
    cleaned_markdown: str


def file_url(path: Path) -> str:
    return FILE_URL_PREFIX + quote(path.resolve().as_posix(), safe="/:")


def resolve_image(src: str, raw_dir: Path) -> Path | None:
    """The file on disk for an `<img src>` of a Manual Page, or None.

    Bare filename -> `raw/images/`, `images/x` -> `raw/`, `<Page>_files/x` -> `raw/htm_docs/`.
    """
    src = unquote(src.strip()).replace("\\", "/")
    if not src or _EXTERNAL.match(src):
        return None
    src = src.removeprefix("./")
    if src.startswith("images/"):
        rel = src
    elif "/" in src:
        rel = f"htm_docs/{src}"
    else:
        rel = f"images/{src}"
    path = (raw_dir / rel).resolve()
    return path if path.is_file() and path.is_relative_to(raw_dir.resolve()) else None


def rewrite_page(raw_html: str, raw_dir: Path) -> str:
    """A Manual Page that is safe to show: scripts stripped, image `src` pointing at file URLs."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on") or (
                attr.lower() in ("href", "src", "action") and str(tag[attr]).strip().lower().startswith("javascript:")
            ):
                del tag[attr]
    for img in soup.find_all("img"):
        path = resolve_image(img.get("src") or "", raw_dir)
        if path is not None:
            img["src"] = file_url(path)
    return str(soup)


def rewrite_cleaned(markdown: str, raw_dir: Path) -> str:
    """A Cleaned Page ready to render: front matter dropped, Screenshots as file URLs, Page Links as plain text."""
    markdown = _FRONT_MATTER.sub("", markdown)

    def image(match: re.Match) -> str:
        path = resolve_image(match.group(1), raw_dir)
        return f"![]({file_url(path)})" if path else ""

    return _MD_PAGE_LINK.sub(lambda m: m.group(1), _MD_IMAGE.sub(image, markdown))


def raw_iframe(rewritten: str, height: int = IFRAME_HEIGHT) -> str:
    return (
        f'<iframe sandbox="allow-same-origin" srcdoc="{html.escape(rewritten)}" '
        f'style="width:100%;height:{height}px;border:1px solid #ccc"></iframe>'
    )


def view_dir() -> Path:
    """Where rewritten copies for **open full page** are written; add it to Gradio's `allowed_paths`."""
    global _view_dir
    if _view_dir is None:
        _view_dir = Path(tempfile.mkdtemp(prefix="navigate_helper_view_"))
    return _view_dir


def _full_page_url(page_file: str, rewritten: str) -> str:
    digest = hashlib.sha256(page_file.encode("utf-8")).hexdigest()[:16]
    out = view_dir() / f"{digest}.html"
    out.write_text(rewritten, encoding="utf-8", newline="\n")
    return file_url(out)


def _message(text: str) -> PageView:
    return PageView(f"<p><em>{html.escape(text)}</em></p>", "", "")


def page_viewer(page_file: str | None, config: Config | None = None) -> PageView:
    """The Page viewer content for one Manual Page, e.g. `page_viewer("Budgetten.htm")`.

    A missing page or Cleaned Page gives a message instead of an error.
    """
    if config is None:
        config = load_config()
    if not page_file:
        return _message("Kies een pagina om te bekijken.")
    name = page_file.strip()
    if Path(name).name != name or not name.lower().endswith((".htm", ".html")):
        return _message(f"Pagina niet gevonden: {name}")
    path = config.htm_dir / name
    if not path.is_file():
        return _message(f"Pagina niet gevonden: {name}")

    raw_dir = config.raw_dir
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rewritten = rewrite_page(raw, raw_dir)
    soup = BeautifulSoup(raw, "html.parser")
    stem = path.stem
    title = collapse(soup.title.get_text()) if soup.title else ""
    title = title or stem

    link = f'<a href="{html.escape(_full_page_url(name, rewritten))}" target="_blank" rel="noopener">open full page</a>'
    heading = f"<h3>{html.escape(title)} · {link}</h3>"

    cleaned_path = config.cleaned_dir / f"{stem}.md"
    if cleaned_path.is_file():
        cleaned = rewrite_cleaned(cleaned_path.read_text(encoding="utf-8"), raw_dir)
    else:
        cleaned = "*Geen Cleaned Page beschikbaar voor deze pagina (draai eerst `clean`).*"
    return PageView(heading, raw_iframe(rewritten), cleaned)
