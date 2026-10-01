"""The ui stage. The chat app is implemented by its own build issue; the Page viewer is ready to embed."""

import gradio as gr

from navigate_helper.config import Config, load_config
from navigate_helper.page_view import page_viewer, view_dir


def build_page_viewer(config: Config | None = None):
    """The Page viewer components, to be called inside a `gr.Blocks`; returns `(page_input, show)`.

    `show(page_file)` loads the viewer; the chat app calls it when a Page Link is chosen.
    """
    heading = gr.HTML()
    with gr.Row():
        raw = gr.HTML(label="Manual Page")
        cleaned = gr.Markdown(label="Cleaned Page")

    def show(page_file: str | None):
        view = page_viewer(page_file, config)
        return view.heading, view.raw_html, view.cleaned_markdown

    return (heading, raw, cleaned), show


def page_viewer_blocks(config: Config | None = None) -> gr.Blocks:
    """A standalone Page viewer: type or pick a page filename and see it."""
    config = config or load_config()
    pages = sorted(p.name for p in config.htm_dir.glob("*.htm")) if config.htm_dir.is_dir() else []
    with gr.Blocks(title="Page viewer") as blocks:
        picker = gr.Dropdown(choices=pages, label="Manual Page", allow_custom_value=True)
        outputs, show = build_page_viewer(config)
        picker.change(show, picker, list(outputs))
    return blocks


def run(config: Config) -> None:
    raise NotImplementedError("the ui stage is not implemented yet")


if __name__ == "__main__":
    _config = load_config()
    page_viewer_blocks(_config).launch(allowed_paths=[str(_config.raw_dir.resolve()), str(view_dir())])
