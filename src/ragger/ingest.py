"""CLI entrypoint: chunk documents under a source directory into the vector store.

Usage: python -m ragger.ingest <source_dir>
"""

import sys

from core.config import load_config
from file_preparing.loading import load_documents
from chunking.chunking import split_documents
from embedding.vectorstore import add_documents, get_vectorstore


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m ragger.ingest <source_dir>")
        sys.exit(1)

    source_dir = sys.argv[1]
    config = load_config()

    documents = load_documents(source_dir)
    chunks = split_documents(documents)
    print(f"Loaded {len(documents)} document(s), split into {len(chunks)} chunk(s).")

    vectorstore = get_vectorstore(config)
    add_documents(vectorstore, chunks)
    print(f"Added {len(chunks)} chunk(s) to '{config.chroma_persist_dir}'.")


if __name__ == "__main__":
    main()
