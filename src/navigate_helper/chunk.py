"""Stage 2 – Chunk: Cleaned Pages (`cleaned/<stem>.md`) to Chunks (`chunked/<stem>.json`).

The rules are in docs/design-decisions.md, section "Stage 2 – Chunk".
"""

import json
import re
import shutil
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Protocol

from tqdm import tqdm

from navigate_helper.config import CHUNK_TOKEN_CAP, CHUNK_TOKEN_CEILING, SHORT_SECTION_CHARS, Config, StageError

PASSAGE_PREFIX = "passage: "
CONTEXT_SEPARATOR = " › "
HISTOGRAM_BUCKET = 100

VERSION_RE = re.compile(r"\bNV\s*(?:&nbsp;| |\s)?(1\.4|2\.0)\b", re.IGNORECASE)
# Anything that looks like "NV" followed by a number; used to find spellings VERSION_RE misses.
_NV_SPELLING = re.compile(r"\bNV(?:\s|&nbsp;|[-_.:])*v?\s*\d+(?:[.,]\d+)?", re.IGNORECASE)
_MENU_ROOT_14 = re.compile(r"\bNV\s*1\.4\b|\bEuroDossier\b", re.IGNORECASE)
_MENU_ROOT_20 = re.compile(r"\bNV\s*2\.0\b", re.IGNORECASE)

_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")
_PAGE_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(<([^>]*)>\)")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((?:<[^>]*>|[^)]*)\)")
_HEADING = re.compile(r"^(#{2,3}) (.*)$")
_LIST_ITEM = re.compile(r"^([-*+]|\d+[.)]) ")
_TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_SPACES = re.compile(r" {2,}")


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


class HFTokenizer:
    """The e5 tokenizer; counts include the special tokens that count towards its 512 limit."""

    def __init__(self, hf_tokenizer):
        self._tokenizer = hf_tokenizer
        hf_tokenizer.model_max_length = 10**9  # we count long texts on purpose

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=True))


def load_tokenizer(model_name: str) -> Tokenizer:
    from transformers import AutoTokenizer

    return HFTokenizer(AutoTokenizer.from_pretrained(model_name))


# --- parsing the Cleaned Page ---------------------------------------------------------------


@dataclass
class Section:
    heading_path: list[str]
    raw: str  # Markdown body, without its own `##` / `###` line
    heading_line: str = ""


def parse_cleaned(markdown: str, stem: str) -> tuple[list[str], str, list[str]]:
    """(menu_path, title, body lines) of a Cleaned Page."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    menu_path: list[str] = []
    if lines and lines[0] == "---":
        end = lines.index("---", 1)
        menu_path = [json.loads(line.strip()[2:]) for line in lines[2:end] if line.strip().startswith("- ")]
        lines = lines[end + 1 :]
    while lines and not lines[0].strip():
        lines.pop(0)
    title = stem
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip() or stem
    return menu_path, title, lines


def _clean_heading(text: str) -> str:
    text = _LINK.sub(lambda m: m.group(1), _IMAGE.sub("", text))
    return _SPACES.sub(" ", text.replace("**", "").replace("__", "")).strip()


def split_sections(title: str, lines: list[str]) -> list[Section]:
    """`##` and `###` start Sections; deeper headings and fenced code stay inside."""
    sections = [Section([title], "")]
    current: list[str] = []
    h2 = ""
    in_fence = False

    def close():
        sections[-1].raw = "\n".join(current).strip("\n")
        current.clear()

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if not match:
            current.append(line)
            continue
        close()
        text = _clean_heading(match.group(2))
        if match.group(1) == "##":
            h2 = text
            path = [title, text]
        else:
            path = [title, h2, text] if h2 else [title, text]
        sections.append(Section(path, "", line))
    close()
    if not sections[0].raw.strip():
        sections.pop(0)  # an empty preamble is not a Section
    return sections


# --- units: the blocks a Chunk is packed from -----------------------------------------------


@dataclass
class Unit:
    """A paragraph, list item or table row, with the Screenshots and Page Links it holds."""

    text: str
    sep: str = "\n\n"
    header: str | None = None  # table header + separator row, repeated at the start of each row group
    has_header: bool = False
    screenshots: list[str] = field(default_factory=list)
    page_links: list[dict] = field(default_factory=list)


def _embed_line(line: str) -> str:
    line = _LINK.sub(lambda m: m.group(1), _IMAGE.sub("", line))
    indent = line[: len(line) - len(line.lstrip())]
    return (indent + _SPACES.sub(" ", line.lstrip())).rstrip()


def _meta(lines: list[str]) -> tuple[list[str], list[dict]]:
    text = "\n".join(lines)
    shots = [m.group(1) for m in _IMAGE.finditer(text)]
    links = [{"title": m.group(1).strip(), "page_file": m.group(2)} for m in _PAGE_LINK.finditer(text)]
    return shots, links


def _blocks(raw: str) -> list[tuple[str, list[str], bool]]:
    """(kind, lines, joined_to_previous) for each paragraph, list item, fenced block and table."""
    blocks: list[tuple[str, list[str], bool]] = []
    in_fence = False
    after_blank = True
    for line in raw.split("\n"):
        stripped = line.strip()
        if in_fence:
            blocks[-1][1].append(line)
            in_fence = not stripped.startswith("```")
            continue
        if not stripped:
            after_blank = True
            continue
        last = blocks[-1][0] if blocks else None
        if stripped.startswith("```"):
            blocks.append(("fence", [line], False))
            in_fence = not (len(stripped) > 3 and stripped.endswith("```"))
        elif stripped.startswith("|"):
            if last == "table" and not after_blank:
                blocks[-1][1].append(line)
            else:
                blocks.append(("table", [line], False))
        elif _LIST_ITEM.match(line):
            blocks.append(("item", [line], last == "item" and not after_blank))
        elif last in ("para", "item") and not after_blank:
            blocks[-1][1].append(line)
        else:
            blocks.append(("para", [line], False))
        after_blank = False
    return blocks


def build_units(raw: str) -> list[Unit]:
    units: list[Unit] = []
    pending_shots: list[str] = []
    pending_links: list[dict] = []

    def add(text: str, sep: str, shots, links, **extra):
        nonlocal pending_shots, pending_links
        if not text.strip():  # image-only: its metadata goes with the text before it, else the text after it
            if units:
                units[-1].screenshots += shots
                units[-1].page_links += links
            else:
                pending_shots, pending_links = pending_shots + shots, pending_links + links
            return
        units.append(Unit(text, sep, screenshots=pending_shots + shots, page_links=pending_links + links, **extra))
        pending_shots, pending_links = [], []

    for kind, lines, joined in _blocks(raw):
        if kind == "table":
            header = None
            body = lines
            if len(lines) >= 2 and _TABLE_SEPARATOR.match(lines[1].strip()):
                header = _embed_line(lines[0]) + "\n" + lines[1].strip()
                body = lines[2:]
                if not body:
                    add(header, "\n\n", *_meta(lines[:1]))
                    continue
            for i, row in enumerate(body):
                text = _embed_line(row)
                if i == 0 and header:
                    add(header + "\n" + text, "\n\n", *_meta(lines[:2] + [row]), header=header, has_header=True)
                else:
                    add(text, "\n", *_meta([row]), header=header)
        elif kind == "fence":
            add("\n".join(lines), "\n\n", *_meta(lines))
        else:
            add("\n".join(_embed_line(l) for l in lines), "\n" if joined else "\n\n", *_meta(lines))
    return units


def join_units(units: list[Unit]) -> str:
    return "".join((u.sep if i else "") + u.text for i, u in enumerate(units))


# --- packing units into Chunks --------------------------------------------------------------

Fits = Callable[[str], bool]


def split_text(text: str, fits: Fits) -> list[str]:
    """Split one oversized block by sentence, then by word. A lone word is never cut."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{current} {sentence}" if current else sentence
        if fits(candidate):
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if fits(sentence):
            current = sentence
            continue
        for word in sentence.split():
            candidate = f"{current} {word}" if current else word
            if current and not fits(candidate):
                pieces.append(current)
                current = word
            else:
                current = candidate
    if current:
        pieces.append(current)
    return pieces


@dataclass
class _Draft:
    units: list[Unit] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    page_links: list[dict] = field(default_factory=list)

    @property
    def body(self) -> str:
        return join_units(self.units)

    def add(self, unit: Unit) -> None:
        self.units.append(unit)
        self.screenshots += unit.screenshots
        self.page_links += unit.page_links


def pack(units: list[Unit], fits: Fits) -> list[_Draft]:
    drafts: list[_Draft] = []
    current = _Draft()

    def starts(unit: Unit) -> Unit:
        if unit.header and not unit.has_header:  # a later row group repeats the table header
            return Unit(unit.header + "\n" + unit.text, "", unit.header, True, unit.screenshots, unit.page_links)
        return Unit(unit.text, "", unit.header, unit.has_header, unit.screenshots, unit.page_links)

    for unit in units:
        if current.units and fits(current.body + unit.sep + unit.text):
            current.add(unit)
            continue
        if current.units:
            drafts.append(current)
            current = _Draft()
        first = starts(unit)
        if fits(first.text):
            current.add(first)
            continue
        pieces = split_text(first.text, fits)
        for i, piece in enumerate(pieces):
            part = Unit(piece, "", screenshots=first.screenshots if i == 0 else [], page_links=first.page_links if i == 0 else [])
            if i < len(pieces) - 1:
                drafts.append(_Draft([part], list(part.screenshots), list(part.page_links)))
            else:
                current.add(part)
    if current.units:
        drafts.append(current)
    return drafts


# --- versions -------------------------------------------------------------------------------


def detect_versions(body: str, menu_path: list[str]) -> list[str]:
    found = {m.group(1) for m in VERSION_RE.finditer(body)}
    root = menu_path[0] if menu_path else ""
    if _MENU_ROOT_14.search(root):
        found.add("1.4")
    if _MENU_ROOT_20.search(root):
        found.add("2.0")
    return sorted(found)


def unmatched_nv_spellings(body: str) -> Counter:
    spellings: Counter = Counter()
    for match in _NV_SPELLING.finditer(body):
        if not VERSION_RE.match(body, match.start()):
            spellings[" ".join(match.group(0).split())] += 1
    return spellings


# --- one page -------------------------------------------------------------------------------


@dataclass
class PageResult:
    chunks: list[dict] = field(default_factory=list)
    unmatched_nv: Counter = field(default_factory=Counter)

    @property
    def empty(self) -> bool:
        return not self.chunks


def chunk_page(
    markdown: str, stem: str, tokenizer: Tokenizer, cap: int = CHUNK_TOKEN_CAP, ceiling: int = CHUNK_TOKEN_CEILING
) -> PageResult:
    menu_path, title, lines = parse_cleaned(markdown, stem)
    sections = split_sections(title, lines)

    def context(path: list[str]) -> str:
        return CONTEXT_SEPARATOR.join(path)

    def tokens(path: list[str], body: str) -> int:
        return tokenizer.count(f"{PASSAGE_PREFIX}{context(path)}\n{body}")

    def fits_section(section: Section) -> bool:
        return tokens(section.heading_path, join_units(build_units(section.raw))) <= cap

    def combine(a: Section, b: Section) -> Section:
        parts = [p for p in (a.raw, b.heading_line, b.raw) if p.strip()]
        return Section(a.heading_path, "\n\n".join(parts), a.heading_line)

    def is_short(section: Section) -> bool:
        return len(join_units(build_units(section.raw)).strip()) < SHORT_SECTION_CHARS

    if not sections:  # nothing but the title: empty after cleaning
        return PageResult()

    merged: list[Section] = []
    pending: Section | None = None
    for section in sections:
        if pending is not None:
            combined = combine(pending, section)
            if fits_section(combined):
                section = combined
            else:
                merged.append(pending)
            pending = None
        if is_short(section):
            pending = section
        else:
            merged.append(section)
    if pending is not None:
        if merged and fits_section(combine(merged[-1], pending)):
            merged[-1] = combine(merged[-1], pending)
        else:
            merged.append(pending)

    result = PageResult()
    for section in merged:
        path = section.heading_path
        drafts = pack(build_units(section.raw), lambda body, p=path: tokens(p, body) <= cap)
        if not drafts:  # a Section of headings or Screenshots only: its context line is still indexed
            shots, links = _meta(section.raw.split("\n"))
            drafts = [_Draft([], shots, links)]
        shots, links = _meta([section.heading_line])  # a heading can hold a Page Link (hub pages)
        drafts[0].screenshots[:0], drafts[0].page_links[:0] = shots, links
        result.chunks += [_chunk(draft, path) for draft in drafts]

    for index, c in enumerate(result.chunks):
        body = c.pop("_body")
        text = f"{context(c['heading_path'])}\n{body}"
        c.update(
            chunk_id=f"{stem}#{index}",
            page_file=f"{stem}.htm",
            page_title=title,
            chunk_index=index,
            versions=detect_versions(body, menu_path),
            char_count=len(text),
            token_count=tokenizer.count(PASSAGE_PREFIX + text),
            menu_path=menu_path,
            text=text,
        )
        if c["token_count"] > ceiling:
            raise StageError(
                f"{c['chunk_id']} has {c['token_count']} tokens, over the {ceiling}-token ceiling; it is never truncated"
            )
        result.unmatched_nv += unmatched_nv_spellings(body)
    return result


def _dedupe(items: list):
    seen, out = set(), []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _chunk(draft: _Draft, path: list[str]) -> dict:
    return {
        "heading_path": list(path),
        "screenshots": _dedupe(draft.screenshots),
        "page_links": _dedupe(draft.page_links),
        "_body": draft.body,
    }


# --- the stage ------------------------------------------------------------------------------


@dataclass
class ChunkReport:
    pages_chunked: int = 0
    chunks: int = 0
    empty_pages: list[str] = field(default_factory=list)
    token_stats: dict[str, float] = field(default_factory=dict)
    histogram: dict[str, int] = field(default_factory=dict)
    max_tokens: int = 0
    max_tokens_chunk: str = ""
    unmatched_nv: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        stats = self.token_stats
        lines = [
            f"Chunks: {self.chunks} from {self.pages_chunked} pages; {len(self.empty_pages)} pages empty after cleaning",
        ]
        if self.chunks:
            lines.append(
                "token counts: " + ", ".join(f"{name} {stats[name]:g}" for name in ("min", "mean", "median", "p90", "p99", "max"))
            )
            lines.append("histogram: " + ", ".join(f"{bucket}: {n}" for bucket, n in self.histogram.items()))
            lines.append(f"max token count: {self.max_tokens} ({self.max_tokens_chunk})")
        total = sum(self.unmatched_nv.values())
        lines.append(f"NV spellings the version regex misses: {total} ({len(self.unmatched_nv)} distinct)")
        if self.unmatched_nv:
            top = sorted(self.unmatched_nv.items(), key=lambda kv: -kv[1])[:20]
            lines.append("  " + ", ".join(f"{spelling!r} x{n}" for spelling, n in top))
        if self.failed:
            lines.append(f"{len(self.failed)} pages failed")
        return "\n".join(lines)


def _percentile(sorted_values: list[int], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(fraction * len(sorted_values)))]


def run(config: Config, page: str | None = None, tokenizer: Tokenizer | None = None) -> ChunkReport:
    cleaned_dir = config.cleaned_dir
    if not cleaned_dir.is_dir():
        raise StageError(f"no Cleaned Pages found at {cleaned_dir}; run `clean` first")
    files = sorted(cleaned_dir.glob("*.md"))
    if page is not None:
        stem = page[:-4] if page.lower().endswith(".htm") else page
        files = [p for p in files if p.stem == stem]
        if not files:
            raise StageError(f"no Cleaned Page called {stem}.md in {cleaned_dir}; run `clean` first")
    else:
        shutil.rmtree(config.chunked_dir, ignore_errors=True)
    config.chunked_dir.mkdir(parents=True, exist_ok=True)
    if tokenizer is None:
        tokenizer = load_tokenizer(config.embedding_model)

    report = ChunkReport()
    counts: list[tuple[int, str]] = []
    unmatched: Counter = Counter()
    for path in tqdm(files, desc="chunk", unit="page", disable=len(files) < 2):
        output = config.chunked_dir / f"{path.stem}.json"
        output.unlink(missing_ok=True)
        try:
            result = chunk_page(path.read_text(encoding="utf-8"), path.stem, tokenizer)
        except Exception as error:  # one bad page must not hide the rest
            report.failed[path.stem] = f"{type(error).__name__}: {error}"
            continue
        unmatched += result.unmatched_nv
        if result.empty:
            report.empty_pages.append(path.stem)
            continue
        output.write_text(json.dumps(result.chunks, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        report.pages_chunked += 1
        report.chunks += len(result.chunks)
        counts += [(c["token_count"], c["chunk_id"]) for c in result.chunks]

    if counts:
        values = sorted(n for n, _ in counts)
        report.max_tokens, report.max_tokens_chunk = max(counts)
        report.token_stats = {
            "min": values[0],
            "mean": round(statistics.fmean(values), 1),
            "median": statistics.median(values),
            "p90": _percentile(values, 0.90),
            "p99": _percentile(values, 0.99),
            "max": values[-1],
        }
        buckets = Counter(n // HISTOGRAM_BUCKET for n in values)
        report.histogram = {
            f"{b * HISTOGRAM_BUCKET}-{(b + 1) * HISTOGRAM_BUCKET - 1}": buckets[b] for b in sorted(buckets)
        }
    report.unmatched_nv = dict(unmatched.most_common())
    print(report.summary())
    if page is None:
        (config.chunked_dir.parent / "chunk_report.json").write_text(
            json.dumps(report.__dict__, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    if report.failed:
        names = ", ".join(sorted(report.failed)[:5])
        raise StageError(f"{len(report.failed)} pages failed to chunk (first: {names}): {next(iter(report.failed.values()))}")
    return report
