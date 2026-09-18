"""Load raw files from disk into cleaned in-memory documents."""

from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document

from file_preparing.html_cleaning import html_to_text


def load_markdown_documents(source_dir: str | Path) -> list[Document]:
    loader = DirectoryLoader(
        str(source_dir),
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    return loader.load()


def load_html_documents(source_dir: str | Path) -> list[Document]:
    source_dir = Path(source_dir)
    documents = []
    for pattern in ("**/*.htm", "**/*.html"):
        for path in sorted(source_dir.glob(pattern)):
            raw = path.read_text(encoding="utf-8", errors="ignore")
            text = html_to_text(raw)
            if text:
                documents.append(Document(page_content=text, metadata={"source": str(path)}))
    return documents


def load_documents(source_dir: str | Path) -> list[Document]:
    return load_markdown_documents(source_dir) + load_html_documents(source_dir)
