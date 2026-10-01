"""Stage 1 – Clean: Manual Pages (`raw/htm_docs/*.htm`) to Cleaned Pages (`cleaned/<stem>.md`).

The rules are in docs/design-decisions.md, section "Stage 1 – Clean".
"""

import json
import re
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag
from markdownify import MarkdownConverter
from tqdm import tqdm

from navigate_helper.config import Config, StageError

SKIP_PAGES = {"index.htm", "rhair_fbody.htm"}
SHORT_PAGE_CHARS = 200
MOSTLY_LINKS_RATIO = 0.6
REPORT_NAME = "_clean_report.json"

# A table cell holding just a filename or URL is text, not a document to fetch.
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

_WHITESPACE = re.compile(r"\s+")
_WRITE_CALL = re.compile(r'RH_Document_Write\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
_TOC_CLASSES = re.compile(r"^(MsoToc\d*|Toc[123])$")
_EXTERNAL = re.compile(r"^(https?:|mailto:)", re.IGNORECASE)
_PLACEHOLDER = "@@TABLE{}@@"
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((?:<[^>]*>|[^)]*)\)")
_MD_IMAGE = re.compile(r"!\[\]\([^)]*\)")


def collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


@dataclass
class CleanedPage:
    markdown: str
    menu_path: list[str]
    text_chars: int
    link_chars: int
    page_links_dropped: list[str] = field(default_factory=list)
    images_dropped: list[str] = field(default_factory=list)

    @property
    def flags(self) -> list[str]:
        if self.text_chars == 0:
            return ["empty"]
        flags = []
        if self.text_chars < SHORT_PAGE_CHARS:
            flags.append("short")
        if self.link_chars / self.text_chars > MOSTLY_LINKS_RATIO:
            flags.append("mostly links")
        return flags


@dataclass
class CleanReport:
    cleaned: int = 0
    page_links_dropped: int = 0
    images_dropped: int = 0
    flagged: dict[str, list[str]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"cleaned {self.cleaned} pages; dropped {self.page_links_dropped} Page Links to missing pages "
            f"and {self.images_dropped} unresolved images; flagged {len(self.flagged)} short or link-only "
            f"pages; {len(self.failed)} failed"
        )


class _Converter(MarkdownConverter):
    """markdownify with `[text](<Page.htm>)` Page Links and `![](path)` Screenshots."""

    def convert_a(self, el, text, parent_tags):
        if el.get("data-pagelink") is not None:
            text = text.strip()
            return f"[{text}](<{el['href']}>)" if text else ""
        return super().convert_a(el, text, parent_tags)

    def convert_img(self, el, text, parent_tags):
        return f"![]({el.get('src', '')})"


def _converter() -> _Converter:
    return _Converter(
        heading_style="ATX",
        bullets="-",
        autolinks=False,
        escape_asterisks=False,
        escape_underscores=False,
        escape_misc=False,
    )


def parse_menu_path(soup: BeautifulSoup) -> list[str]:
    """The breadcrumb path in the first `<script>` of `<body>`, or an empty list."""
    body = soup.body
    script = body.find("script") if body else None
    if script is None:
        return []
    parts = []
    for raw in _WRITE_CALL.findall(script.get_text()):
        parts.append(raw.replace('\\"', '"').replace("<\\/", "</").replace("\\/", "/").replace("\\\\", "\\"))
    text = collapse(BeautifulSoup("".join(parts), "html.parser").get_text())
    return [step.strip() for step in text.split(" / ") if step.strip()]


def _remove_junk(soup: BeautifulSoup) -> None:
    for node in soup.find_all(string=lambda s: isinstance(s, (Comment, Declaration, Doctype, ProcessingInstruction))):
        node.extract()
    for tag in soup.find_all(["head", "script", "style", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(class_=_TOC_CLASSES):
        tag.decompose()


def _normalise_whitespace(soup: BeautifulSoup) -> None:
    for node in soup.find_all(string=True):
        if node.find_parent("pre") is None:
            node.replace_with(NavigableString(_WHITESPACE.sub(" ", str(node))))


def _resolve_image(src: str, raw_dir: Path) -> str | None:
    """The `raw/`-relative path of an image on disk, or None."""
    src = unquote(src.strip()).replace("\\", "/")
    if not src or _EXTERNAL.match(src) or src.startswith("//"):
        return None
    if src.startswith("./"):
        src = src[2:]
    if src.startswith("images/"):
        rel = src
    elif "/" in src:
        rel = f"htm_docs/{src}"
    else:
        rel = f"images/{src}"
    return rel if (raw_dir / rel).is_file() else None


def _rewrite_images(soup: BeautifulSoup, raw_dir: Path, dropped: list[str]) -> None:
    for img in soup.find_all("img"):
        rel = _resolve_image(img.get("src") or "", raw_dir)
        if rel is None:
            dropped.append(img.get("src") or "")
            img.decompose()
        else:
            img.attrs = {"src": rel}


def _rewrite_links(soup: BeautifulSoup, pages: dict[str, str], dropped: list[str]) -> None:
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            a.unwrap()
            continue
        if _EXTERNAL.match(href) or href.lower().split("#")[0].endswith(".pdf"):
            keep = a.get_text().strip() or a.find("img")
            if keep:
                a.attrs = {"href": href}
            else:
                a.decompose()
            continue
        target = unquote(href.split("#")[0]).replace("\\", "/")
        target = target[2:] if target.startswith("./") else target
        canonical = pages.get(target.lower()) if target.lower().endswith((".htm", ".html")) else None
        if canonical is None:
            if target.lower().endswith((".htm", ".html")):
                dropped.append(target)
            a.unwrap()
        elif not a.get_text().strip():
            a.unwrap() if a.find("img") else a.decompose()
        else:
            a.attrs = {"href": canonical, "data-pagelink": ""}


def _rewrite_headings(soup: BeautifulSoup, title: str) -> None:
    headings = []
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        text = collapse(h.get_text())
        if not text or text.casefold() == title.casefold():
            h.decompose()
        else:
            headings.append(h)
    levels = sorted({int(h.name[1]) for h in headings})
    new_level = {level: min(6, 2 + i) for i, level in enumerate(levels)}
    for h in headings:
        h.name = f"h{new_level[int(h.name[1])]}"


def _cell_markdown(cell: Tag, converter: _Converter) -> str:
    html = "".join(str(child) for child in cell.contents)
    text = converter.convert_soup(BeautifulSoup(html, "html.parser"))
    return collapse(text).replace("|", "\\|")


def _grid(table: Tag, converter: _Converter) -> list[list[str]]:
    """Rows of cell text, with merged cells repeated into each spanned position."""
    grid: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}
    for tr in table.find_all("tr"):
        row: list[str] = []

        def fill_pending():
            while len(row) in pending:
                left, text = pending[len(row)]
                row.append(text)
                if left > 1:
                    pending[len(row) - 1] = (left - 1, text)
                else:
                    del pending[len(row) - 1]

        for cell in tr.find_all(["td", "th"], recursive=False):
            fill_pending()
            text = _cell_markdown(cell, converter)
            colspan = max(1, int(re.sub(r"\D", "", cell.get("colspan") or "") or 1))
            rowspan = max(1, int(re.sub(r"\D", "", cell.get("rowspan") or "") or 1))
            for _ in range(colspan):
                if rowspan > 1:
                    pending[len(row)] = (rowspan - 1, text)
                row.append(text)
        fill_pending()
        grid.append(row)
    return grid


def _pipe_table(grid: list[list[str]]) -> str:
    grid = [row for row in grid if any(row)]
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    lines = []
    for i, row in enumerate(grid):
        row = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(row) + " |")
        if i == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def _rewrite_tables(soup: BeautifulSoup, converter: _Converter) -> list[str]:
    """Replace each table by a placeholder paragraph; return the pipe tables in placeholder order."""
    rendered: list[str] = []
    for table in reversed(soup.find_all("table")):
        if table.find_parent(["td", "th"]) is not None:
            table.replace_with(NavigableString(" " + " ".join(table.stripped_strings) + " "))
            continue
        cells = table.find_all(["td", "th"])
        if len(cells) == 1 or (len(cells) == 2 and table.find("img") is not None):
            wrapper = soup.new_tag("div")
            for cell in cells:
                part = soup.new_tag("div")
                for child in list(cell.contents):
                    part.append(child)
                wrapper.append(part)
            table.replace_with(wrapper)
            continue
        rendered.append(_pipe_table(_grid(table, converter)))
        marker = soup.new_tag("p")
        marker.string = _PLACEHOLDER.format(len(rendered) - 1)
        table.replace_with(marker)
    return rendered


def _front_matter(menu_path: list[str]) -> str:
    if not menu_path:
        return ""
    items = "\n".join(f"  - {json.dumps(step, ensure_ascii=False)}" for step in menu_path)
    return f"---\nmenu_path:\n{items}\n---\n\n"


def _measure(body: str) -> tuple[int, int]:
    """(text characters, link-text characters) of a Cleaned Page body."""
    no_images = _MD_IMAGE.sub("", body)
    link_chars = sum(len(collapse(m.group(1))) for m in _MD_LINK.finditer(no_images))
    plain = _MD_LINK.sub(lambda m: m.group(1), no_images)
    plain = re.sub(r"^\s*(#+|[-|]+|---)\s*", "", plain, flags=re.MULTILINE)
    plain = re.sub(r"[|#*\\-]", " ", plain)
    return len(collapse(plain)), link_chars


def clean_html(html: str, stem: str, pages: dict[str, str], raw_dir: Path) -> CleanedPage:
    """Turn one Manual Page into a Cleaned Page.

    `pages` maps lower-cased page filenames to their real filenames (the Page Link targets that exist).
    """
    soup = BeautifulSoup(html, "html.parser")
    menu_path = parse_menu_path(soup)
    title = collapse(soup.title.get_text()) if soup.title else ""
    title = title or stem

    _remove_junk(soup)
    _normalise_whitespace(soup)
    links_dropped: list[str] = []
    images_dropped: list[str] = []
    _rewrite_links(soup, pages, links_dropped)
    _rewrite_images(soup, raw_dir, images_dropped)
    _rewrite_headings(soup, title)
    converter = _converter()
    tables = _rewrite_tables(soup, converter)

    body = converter.convert_soup(soup)
    for i, table in enumerate(tables):
        body = body.replace(_PLACEHOLDER.format(i), "\n\n" + table + "\n\n")
    lines = [line.rstrip() for line in body.replace("\xa0", " ").splitlines()]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    text_chars, link_chars = _measure(body)
    markdown = _front_matter(menu_path) + f"# {title}\n\n" + body
    return CleanedPage(markdown.rstrip() + "\n", menu_path, text_chars, link_chars, links_dropped, images_dropped)


def run(config: Config, page: str | None = None) -> CleanReport:
    htm_dir = config.htm_dir
    if not htm_dir.is_dir():
        raise StageError(f"no Manual Pages found at {htm_dir}; put the export in raw/htm_docs/")
    files = sorted(p for p in htm_dir.glob("*.htm") if p.name.lower() not in SKIP_PAGES)
    pages = {p.name.lower(): p.name for p in files}
    if page is not None:
        stem = page[:-4] if page.lower().endswith(".htm") else page
        files = [p for p in files if p.stem == stem]
        if not files:
            raise StageError(f"no Manual Page called {stem}.htm in {htm_dir}")
    else:
        shutil.rmtree(config.cleaned_dir, ignore_errors=True)
    config.cleaned_dir.mkdir(parents=True, exist_ok=True)

    report = CleanReport()
    for path in tqdm(files, desc="clean", unit="page", disable=len(files) < 2):
        try:
            result = clean_html(path.read_text(encoding="utf-8-sig"), path.stem, pages, config.raw_dir)
        except Exception as error:  # one bad page must not hide the rest
            report.failed[path.name] = f"{type(error).__name__}: {error}"
            continue
        (config.cleaned_dir / f"{path.stem}.md").write_text(result.markdown, encoding="utf-8", newline="\n")
        report.cleaned += 1
        report.page_links_dropped += len(result.page_links_dropped)
        report.images_dropped += len(result.images_dropped)
        if result.flags:
            report.flagged[path.name] = result.flags

    if page is None:
        (config.cleaned_dir / REPORT_NAME).write_text(
            json.dumps(report.__dict__, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    print(report.summary())
    if report.failed:
        names = ", ".join(sorted(report.failed)[:5])
        raise StageError(f"{len(report.failed)} pages failed to clean (first: {names}); see {REPORT_NAME}")
    return report
