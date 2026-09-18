"""Chroma-backed vector store for document chunks."""

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from core.config import Config


def get_embeddings(config: Config) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=config.embedding_model)


def get_vectorstore(config: Config) -> Chroma:
    return Chroma(
        collection_name=config.chroma_collection_name,
        embedding_function=get_embeddings(config),
        persist_directory=config.chroma_persist_dir,
    )


def add_documents(vectorstore: Chroma, documents: list[Document]) -> None:
    vectorstore.add_documents(documents)
