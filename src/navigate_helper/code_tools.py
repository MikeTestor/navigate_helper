"""Read-only tools over the Code Checkout: `grep`, `list`, `read`.

Read-only, confinement to the root, the extension allowlist and the excluded folders are enforced here,
not in the prompt (ADR 0001).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ALLOWED_EXTENSIONS = frozenset({".p", ".i", ".w", ".cls", ".v", ".cs", ".xaml", ".xml", ".df", ".md"})
EXCLUDED_FOLDERS = frozenset({"data", "projects", ".builder", ".claude", ".vs", "bin", "obj"})
MAX_READ_LINES = 400
MAX_GREP_MATCHES = 100


class CodeToolError(ValueError):
    """A tool call was refused or cannot be served; the message goes back to the model."""


@dataclass(frozen=True)
class CodeRead:
    path: str
    start: int
    end: int
    total_lines: int
    text: str
    truncated: bool


@dataclass(frozen=True)
class CodeMatch:
    path: str
    line: int
    text: str


class CodeTools:
    def __init__(self, root: Path):
        root = Path(root)
        if not root.is_dir():
            raise CodeToolError(f"the Code Checkout {root} is not a folder")
        self._root = root.resolve()

    def list(self, path: str = ".") -> list[str]:
        """Allowed files and folders directly under `path`, relative to the root; folders end in `/`."""
        folder = self._resolve(path)
        if not folder.is_dir():
            raise CodeToolError(f"{path} is not a folder")
        entries = []
        for entry in sorted(folder.iterdir(), key=lambda e: e.name):
            try:
                resolved = self._resolve(entry)
            except CodeToolError:
                continue
            if resolved.is_dir():
                entries.append(self._relative(resolved) + "/")
            elif resolved.suffix.lower() in ALLOWED_EXTENSIONS:
                entries.append(self._relative(resolved))
        return entries

    def read(self, path: str, start: int = 1, limit: int = MAX_READ_LINES) -> CodeRead:
        """Lines `start`..`start+limit-1` (1-based), at most `MAX_READ_LINES`; `truncated` if more follow."""
        file = self._resolve_file(path)
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start)
        count = max(0, min(limit, MAX_READ_LINES))
        chosen = lines[start - 1 : start - 1 + count]
        end = start + len(chosen) - 1 if chosen else start - 1
        return CodeRead(
            path=self._relative(file),
            start=start,
            end=end,
            total_lines=len(lines),
            text="\n".join(chosen),
            truncated=end < len(lines),
        )

    def grep(
        self, pattern: str, path: str = ".", ignore_case: bool = True, max_matches: int = MAX_GREP_MATCHES
    ) -> list[CodeMatch]:
        """Lines matching the regex `pattern` in allowed files under `path`, at most `max_matches`."""
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as error:
            raise CodeToolError(f"invalid pattern: {error}") from error
        limit = min(max_matches, MAX_GREP_MATCHES)
        matches: list[CodeMatch] = []
        for file in self._files(self._resolve(path)):
            for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(CodeMatch(self._relative(file), number, line.strip()))
                    if len(matches) >= limit:
                        return matches
        return matches

    def _files(self, start: Path):
        if start.is_file():
            if start.suffix.lower() in ALLOWED_EXTENSIONS:
                yield start
            return
        for folder, subfolders, names in os.walk(start):
            subfolders[:] = sorted(d for d in subfolders if d.lower() not in EXCLUDED_FOLDERS)
            for name in sorted(names):
                if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue
                try:
                    yield self._resolve(Path(folder) / name)
                except CodeToolError:
                    continue

    def _resolve_file(self, path: str) -> Path:
        file = self._resolve(path)
        if not file.is_file():
            raise CodeToolError(f"{path} is not a file")
        if file.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise CodeToolError(f"{path} has an extension that is not readable")
        return file

    def _resolve(self, path: str | Path) -> Path:
        resolved = (self._root / path).resolve()
        try:
            parts = resolved.relative_to(self._root).parts
        except ValueError:
            raise CodeToolError(f"{path} is outside the Code Checkout") from None
        if any(part.lower() in EXCLUDED_FOLDERS for part in parts):
            raise CodeToolError(f"{path} is in an excluded folder")
        if not resolved.exists():
            raise CodeToolError(f"{path} does not exist")
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix() or "."
