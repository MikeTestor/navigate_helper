"""Retrieve relevant chunks and generate an answer grounded in them."""

from langchain_chroma import Chroma

from core.config import Config
from ragger.llm import get_chat_fn

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the question using only the "
    "provided context. If the context doesn't contain the answer, say so."
)


def answer(question: str, vectorstore: Chroma, config: Config, k: int = 4) -> str:
    docs = vectorstore.similarity_search(question, k=k)
    context = "\n\n---\n\n".join(doc.page_content for doc in docs)
    user_prompt = f"Context:\n{context}\n\nQuestion: {question}"
    chat = get_chat_fn(config)
    return chat(SYSTEM_PROMPT, user_prompt)
