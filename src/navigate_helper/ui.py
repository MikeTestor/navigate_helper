"""The ui stage: the Gradio dev app. It knows only `Answer`; the rules are in docs/design-decisions.md,
section "Stages 4 and 5 – Gradio dev app"."""

from dataclasses import dataclass, field

import gradio as gr

from navigate_helper.ask import Answer, build_assistant
from navigate_helper.config import Config, load_config
from navigate_helper.page_view import page_viewer, resolve_image, view_dir


def build_page_viewer(config: Config | None = None):
    """The Page viewer components, to be called inside a `gr.Blocks`; returns `((heading, raw, cleaned), show, tabs)`.

    `show(page_file)` loads the viewer; the chat app calls it when a Page Link is chosen. The heading sits above
    `tabs` (Manual page, Markdown page); the caller can re-enter `tabs` to add its own tab.
    """
    heading = gr.HTML()
    with gr.Tabs() as tabs:  # tabs rather than columns: each gets the full width of the narrow right-hand side
        with gr.Tab("Manual page"):
            raw = gr.HTML()
        with gr.Tab("Markdown page"):
            cleaned = gr.Markdown()

    def show(page_file: str | None):
        view = page_viewer(page_file, config)
        return view.heading, view.raw_html, view.cleaned_markdown

    return (heading, raw, cleaned), show, tabs


def page_viewer_blocks(config: Config | None = None) -> gr.Blocks:
    """A standalone Page viewer: type or pick a page filename and see it."""
    config = config or load_config()
    pages = sorted(p.name for p in config.htm_dir.glob("*.htm")) if config.htm_dir.is_dir() else []
    with gr.Blocks(title="Page viewer") as blocks:
        picker = gr.Dropdown(choices=pages, label="Manual Page", allow_custom_value=True)
        outputs, show, _ = build_page_viewer(config)
        picker.change(show, picker, list(outputs))
    return blocks


QUESTION_ID = "question"
# Autofocus covers opening the app; this refocuses the question box when the browser tab is selected again.
FOCUS_QUESTION_JS = (
    "() => { const focus = () => document.querySelector('#" + QUESTION_ID + " textarea')?.focus();"
    " window.addEventListener('focus', focus); }"
)

CHAT_ID = "chat"
LEFT_ID = "left"
# Gradio puts a message's copy button below the message; this puts it to the right of the text, top-aligned.
# (20px is the message row's own top margin.)
CHAT_CSS = f"""
/* The question box stays at the bottom left: the left column fills the window and the chat takes what is left. */
#{LEFT_ID} {{ height: calc(100vh - 100px); min-height: 420px; }}
#{CHAT_ID} {{ height: auto !important; flex: 1 1 0 !important; min-height: 200px; }}
#{CHAT_ID} .message-wrap {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 4px; }}
#{CHAT_ID} .message-wrap > .message-row {{ grid-column: 1; }}
#{CHAT_ID} .message-wrap > .message-buttons {{ grid-column: 2; align-self: start; margin: 20px 0 0 0; width: auto; }}
"""

DEBUG_HEADERS = ["chunk_id", "page title", "heading path", "score", "cited", "text"]


@dataclass
class AnswerView:
    """An Answer turned into UI values, so the logic is testable without launching Gradio."""

    gallery: list[tuple[str, str]] = field(default_factory=list)
    page_link_choices: list[tuple[str, str]] = field(default_factory=list)
    debug_rows: list[list] = field(default_factory=list)
    debug_notes: str = ""


def answer_view(answer: Answer, config: Config) -> AnswerView:
    gallery, seen = [], set()
    for chunk in answer.cited:
        for src in chunk.screenshots:
            if src in seen:
                continue
            seen.add(src)
            path = resolve_image(src, config.raw_dir)
            if path is not None:
                gallery.append((str(path), f"{chunk.page_title} / {src.rsplit('/', 1)[-1]}"))

    # The Answer's own pages first (the closest ones when it is not covered), then the Manual's Page Links.
    links, seen_pages = [], set()
    candidates = [(p["page_title"], p["page_file"]) for p in answer.source_pages]
    candidates += [(link["title"], link["page_file"]) for link in answer.page_links]
    for title, page_file in candidates:
        if page_file not in seen_pages:
            seen_pages.add(page_file)
            links.append((title, page_file))

    rows = [
        [c.chunk_id, c.page_title, " > ".join(c.heading_path), c.score, "ja" if c.cited else "", c.text]
        for c in answer.retrieved
    ]
    notes = []
    if answer.error:
        notes.append(f"**error:** {answer.error}")
    if answer.dropped_citation_ids:
        notes.append("**Genegeerde bronverwijzingen:** " + ", ".join(answer.dropped_citation_ids))
    if answer.uncited:
        notes.append("**let op:** geen geldige bronverwijzing")
    return AnswerView(gallery, links, rows, "\n\n".join(notes))


def merge_page_links(shown: list[tuple[str, str]], new: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The accumulated Page Link list as `(title, page_file)`: this Answer's pages first, earlier ones below.

    A page that is already in the list moves up instead of appearing twice.
    """
    new = list(dict((page_file, (title, page_file)) for title, page_file in new).values())
    new_files = {page_file for _, page_file in new}
    return new + [item for item in shown if item[1] not in new_files]


def respond(assistant, config: Config, message: str, history: list[dict], shown=()):
    """One chat turn: returns (history, textbox, page link radio, gallery, large screenshot, debug rows, debug notes,
    shown links)."""
    shown = list(shown)
    if not message.strip():
        return history, message, *(gr.update() for _ in range(5)), shown
    first_question = not history
    history = history + [{"role": "user", "content": message}]
    try:
        answer = assistant.ask(message)
    except Exception as error:  # retrieval and config errors raise from ask
        history.append({"role": "assistant", "content": f"Er ging iets mis: {type(error).__name__}: {error}"})
        return history, "", gr.update(), [], large_screenshot(None), [], f"**error:** {error}", shown
    view = answer_view(answer, config)
    history.append({"role": "assistant", "content": answer.text})
    shown = merge_page_links(shown, view.page_link_choices)
    radio = {"choices": shown, "visible": bool(shown)}
    if first_question and view.page_link_choices:
        # Only the first Answer preselects a page (which loads the viewer); later Answers leave the viewer alone.
        radio["value"] = view.page_link_choices[0][1]
    first_shot = view.gallery[0] if view.gallery else None  # section 2 of the Screenshots tab starts on the first
    return (
        history, "", gr.update(**radio), view.gallery, large_screenshot(first_shot), view.debug_rows, view.debug_notes,
        shown,
    )


def large_screenshot(shot: tuple[str, str] | None):
    """The large Screenshot view for a `(path, caption)` gallery item, or empty for None."""
    path, caption = shot if shot else (None, "Screenshot")
    return gr.update(value=path, label=caption)


def select_screenshot(event: gr.SelectData):
    """The gallery's select event: show the clicked thumbnail large."""
    item = event.value
    return large_screenshot((item["image"]["path"], item.get("caption") or ""))


def clear_page_links():
    return gr.update(choices=[], value=None, visible=False), []


def keep_viewer_when_unselected(show):
    """Wrap the Page viewer's `show` so that clearing the radio (a new Answer) leaves the viewer as it is."""

    def wrapped(page_file: str | None):
        return show(page_file) if page_file else (gr.update(), gr.update(), gr.update())

    return wrapped


def chat_blocks(assistant, config: Config) -> gr.Blocks:
    """Chat on the left, tabs (Manual page, Markdown page, Debug) on the right."""
    with gr.Blocks(title="Navigate Helper") as blocks:
        with gr.Row():
            with gr.Column(scale=2, elem_id=LEFT_ID):
                chat = gr.Chatbot(elem_id=CHAT_ID)
                links = gr.Radio(label="Page Links (kies om te openen)", visible=False)
                clear_links = gr.Button("Wis lijst", size="sm")
                box = gr.Textbox(placeholder="Stel een vraag", show_label=False, elem_id=QUESTION_ID, autofocus=True)
            with gr.Column(scale=3):
                viewer_outputs, show, tabs = build_page_viewer(config)
                with tabs, gr.Tab("Debug"):
                    table = gr.Dataframe(headers=DEBUG_HEADERS, interactive=False, wrap=True)
                    notes = gr.Markdown()
                with tabs, gr.Tab("Screenshots"):
                    gallery = gr.Gallery(label="Alle screenshots", columns=4, height=220, allow_preview=False)
                    large = gr.Image(label="Screenshot", interactive=False)
        shown = gr.State([])  # the accumulated Page Links, as (title, page_file)
        box.submit(
            lambda message, history, shown: respond(assistant, config, message, history, shown),
            [box, chat, shown],
            [chat, box, links, gallery, large, table, notes, shown],
        )
        gallery.select(select_screenshot, None, large)
        clear_links.click(clear_page_links, None, [links, shown])
        links.change(keep_viewer_when_unselected(show), links, list(viewer_outputs))
    return blocks


def run(config: Config) -> None:
    assistant = build_assistant(config)  # once, at startup (slow: loads the e5 model)
    chat_blocks(assistant, config).launch(
        allowed_paths=[str(config.raw_dir.resolve()), str(view_dir())], js=FOCUS_QUESTION_JS, css=CHAT_CSS
    )


if __name__ == "__main__":
    _config = load_config()
    page_viewer_blocks(_config).launch(allowed_paths=[str(_config.raw_dir.resolve()), str(view_dir())])
