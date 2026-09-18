"""Gradio chat UI for querying the RAG pipeline."""

import gradio as gr

from core.config import load_config
from ragger.rag import answer
from embedding.vectorstore import get_vectorstore


def main() -> None:
    config = load_config()
    vectorstore = get_vectorstore(config)

    def respond(message: str, history: list[dict]) -> str:
        return answer(message, vectorstore, config)

    gr.ChatInterface(
        respond,
        title="Ragger",
        type="messages",
    ).launch()


if __name__ == "__main__":
    main()
