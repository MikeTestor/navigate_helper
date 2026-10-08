"""Page viewer content: a raw Manual Page next to its Cleaned Page.

The rules are in docs/design-decisions.md, section "Stages 4 and 5 – Gradio dev app". Nothing here imports Gradio.
"""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from navigate_helper.clean import collapse
from navigate_helper.config import Config, load_config

FILE_URL_PREFIX = "/gradio_api/file="
FULL_PAGE_PREFIX = "/manual/"  # where `ui.manual_app` serves a Manual Page for **open full page**
IFRAME_HEIGHT = "calc(100vh - 216px)"  # bottom edge level with the question box: 100px for the left column, 116px for the heading and tabs above the page
IFRAME_MIN_HEIGHT = "300px"

_EXTERNAL = re.compile(r"^(https?:|mailto:|data:|//)", re.IGNORECASE)
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n\n?", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[\]\(([^)]*)\)")
_MD_PAGE_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(<[^>]*>\)")
# Runs inside the iframe; a click on a link to another Manual Page asks the app to load that page in the viewer.
IFRAME_LINK_SCRIPT = (
    "<script>document.addEventListener('click', function (e) {"
    " var a = e.target.closest && e.target.closest('a[data-page]'); if (!a) return;"
    " e.preventDefault(); parent.postMessage({navigateHelperPage: a.getAttribute('data-page')}, '*'); });</script>"
)


@dataclass(frozen=True)
class PageView:
    """What the Page viewer shows: an HTML heading, the raw page iframe, and the Cleaned Page as Markdown.

    `markdown_source` is the Cleaned Page file as written by `clean` (for copying); empty when there is none.
    """

    heading: str
    raw_html: str
    cleaned_markdown: str
    markdown_source: str = ""


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


def linked_page(href: str, raw_dir: Path) -> str | None:
    """The Manual Page file a relative link points at (without `#anchor`), or None when there is no such page."""
    name = unquote(href.strip().split("#")[0]).replace("\\", "/")
    if not name.lower().endswith((".htm", ".html")) or _EXTERNAL.match(name) or "/" in name:
        return None
    return name if (raw_dir / "htm_docs" / name).is_file() else None


def rewrite_page(raw_html: str, raw_dir: Path, links: str = "plain") -> str:
    """A Manual Page that is safe to show: scripts stripped, image `src` pointing at file URLs, relative links as plain text.

    `links` says what happens to a link to another Manual Page that exists: "plain" (plain text), "viewer" (kept with
    `data-page` for the iframe script) or "served" (kept as a relative link, for the page served at `FULL_PAGE_PREFIX`).
    Links to pages that do not exist are always plain text.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on") or (
                attr.lower() in ("href", "src", "action") and str(tag[attr]).strip().lower().startswith("javascript:")
            ):
                del tag[attr]
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.startswith("#") or _EXTERNAL.match(href):
            continue
        page = linked_page(href, raw_dir) if links != "plain" else None
        if page and links == "viewer":
            link["data-page"] = page
            link["href"] = "#"
        elif page:
            anchor = href.partition("#")[2]
            link["href"] = quote(page) + ("#" + anchor if anchor else "")
        else:
            link.unwrap()  # a relative link cannot resolve inside the srcdoc iframe
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


def raw_iframe(rewritten: str, height: str = IFRAME_HEIGHT) -> str:
    # In a srcdoc iframe a bare `#anchor` resolves against the app's URL and loads it in the frame; `about:srcdoc#anchor` scrolls.
    soup = BeautifulSoup(rewritten, "html.parser")
    for link in soup.find_all("a", href=True):
        if link["href"].startswith("#"):
            link["href"] = "about:srcdoc" + link["href"]
    # allow-scripts is for IFRAME_LINK_SCRIPT only: the page's own scripts are stripped by `rewrite_page`.
    document = str(soup) + IFRAME_LINK_SCRIPT
    return (
        f'<iframe sandbox="allow-same-origin allow-scripts" srcdoc="{html.escape(document)}" '
        f'style="width:100%;height:{height};min-height:{IFRAME_MIN_HEIGHT};border:1px solid #ccc"></iframe>'
    )


def served_page(name: str, config: Config) -> str | None:
    """A Manual Page ready to serve at `FULL_PAGE_PREFIX + name` (scripts stripped, image URLs and links rewritten), or None."""
    if not name or Path(name).name != name or not name.lower().endswith((".htm", ".html")):
        return None
    path = config.htm_dir / name
    if not path.is_file():
        return None
    return rewrite_page(path.read_text(encoding="utf-8-sig", errors="replace"), config.raw_dir, links="served")


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
    in_viewer = rewrite_page(raw, raw_dir, links="viewer")
    soup = BeautifulSoup(raw, "html.parser")
    stem = path.stem
    title = collapse(soup.title.get_text()) if soup.title else ""
    title = title or stem

    link = f'<a href="{html.escape(FULL_PAGE_PREFIX + quote(name))}" target="_blank" rel="noopener">open full page</a>'
    heading = f"<h3>{html.escape(title)} · {link}</h3>"

    cleaned_path = config.cleaned_dir / f"{stem}.md"
    source = ""
    if cleaned_path.is_file():
        source = cleaned_path.read_text(encoding="utf-8")
        cleaned = rewrite_cleaned(source, raw_dir)
    else:
        cleaned = "*Geen Cleaned Page beschikbaar voor deze pagina (draai eerst `clean`).*"
    return PageView(heading, raw_iframe(in_viewer), cleaned, source)
