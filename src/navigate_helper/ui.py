"""The ui stage: the Gradio dev app. It knows only `Answer`; the rules are in docs/design-decisions.md,
section "Stages 4 and 5 – Gradio dev app"."""

from dataclasses import dataclass, field

import gradio as gr

from navigate_helper.ask import Answer, build_assistant
from navigate_helper.config import Config, load_config
from navigate_helper.page_view import page_viewer, resolve_image, view_dir


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


QUESTION_ID = "question"
# Autofocus covers opening the app; this refocuses the question box when the browser tab is selected again.
FOCUS_QUESTION_JS = (
    "() => { const focus = () => document.querySelector('#" + QUESTION_ID + " textarea')?.focus();"
    " window.addEventListener('focus', focus); }"
)

CHAT_ID = "chat"
# Gradio puts a message's copy button below the message; this puts it to the right of the text, top-aligned.
# (20px is the message row's own top margin.)
CHAT_CSS = f"""
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


NEW_MARK = "nieuw · "


def merge_page_links(shown: list[tuple[str, str]], new: list[tuple[str, str]]):
    """The accumulated Page Link list: this Answer's pages first (marked as new), earlier ones below.

    Returns `(shown, choices)`; `shown` is the plain `(title, page_file)` list to keep, `choices` the radio choices.
    A page that is already in the list moves up instead of appearing twice.
    """
    new = list(dict(((page_file, (title, page_file)) for title, page_file in new)).values())
    new_files = {page_file for _, page_file in new}
    merged = new + [item for item in shown if item[1] not in new_files]
    choices = [((NEW_MARK if page_file in new_files else "") + title, page_file) for title, page_file in merged]
    return merged, choices


def respond(assistant, config: Config, message: str, history: list[dict], shown=()):
    """One chat turn: returns (history, textbox, page link radio, gallery, debug rows, debug notes, shown links)."""
    shown = list(shown)
    if not message.strip():
        return history, message, gr.update(), gr.update(), gr.update(), gr.update(), shown
    first_question = not history
    history = history + [{"role": "user", "content": message}]
    try:
        answer = assistant.ask(message)
    except Exception as error:  # retrieval and config errors raise from ask
        history.append({"role": "assistant", "content": f"Er ging iets mis: {type(error).__name__}: {error}"})
        return history, "", gr.update(), [], [], f"**error:** {error}", shown
    view = answer_view(answer, config)
    history.append({"role": "assistant", "content": answer.text})
    shown, choices = merge_page_links(shown, view.page_link_choices)
    radio = {"choices": choices, "visible": bool(choices)}
    if first_question and view.page_link_choices:
        # Only the first Answer preselects a page (which loads the viewer); later Answers leave the viewer alone.
        radio["value"] = view.page_link_choices[0][1]
    return history, "", gr.update(**radio), view.gallery, view.debug_rows, view.debug_notes, shown


def clear_page_links():
    return gr.update(choices=[], value=None, visible=False), []


def keep_viewer_when_unselected(show):
    """Wrap the Page viewer's `show` so that clearing the radio (a new Answer) leaves the viewer as it is."""

    def wrapped(page_file: str | None):
        return show(page_file) if page_file else (gr.update(), gr.update(), gr.update())

    return wrapped


def chat_blocks(assistant, config: Config) -> gr.Blocks:
    """Chat on the left, tabs (Page viewer, Debug) on the right."""
    with gr.Blocks(title="Navigate Helper") as blocks:
        with gr.Row():
            with gr.Column(scale=2):
                chat = gr.Chatbot(height=420, elem_id=CHAT_ID)
                links = gr.Radio(label="Page Links (kies om te openen)", visible=False)
                clear_links = gr.Button("Wis lijst", size="sm")
                gallery = gr.Gallery(label="Screenshots", columns=3, height=200)
                box = gr.Textbox(placeholder="Stel een vraag", show_label=False, elem_id=QUESTION_ID, autofocus=True)
            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("Page viewer"):
                        viewer_outputs, show = build_page_viewer(config)
                    with gr.Tab("Debug"):
                        table = gr.Dataframe(headers=DEBUG_HEADERS, interactive=False, wrap=True)
                        notes = gr.Markdown()
        shown = gr.State([])  # the accumulated Page Links, as (title, page_file)
        box.submit(
            lambda message, history, shown: respond(assistant, config, message, history, shown),
            [box, chat, shown],
            [chat, box, links, gallery, table, notes, shown],
        )
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
