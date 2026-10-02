"""The ui stage: the Gradio dev app. It knows only `Answer`; the rules are in docs/design-decisions.md,
section "Stages 4 and 5 – Gradio dev app"."""

from dataclasses import dataclass, field

import gradio as gr

from navigate_helper.ask import Answer, build_assistant
from navigate_helper.config import Config, load_config
from navigate_helper.page_view import page_viewer, resolve_image, view_dir


VIEWER_OUTPUT_COUNT = 4  # heading, raw page, Cleaned Page, Markdown source
# Copies the Markdown source and shows "Gekopieerd" on the clicked button for a moment.
COPY_MARKDOWN_JS = (
    "async (md) => { await navigator.clipboard.writeText(md || '');"
    " const button = document.activeElement;"
    " if (button) { const label = button.textContent; button.textContent = 'Gekopieerd ✓';"
    " setTimeout(() => { button.textContent = label; }, 1500); } }"
)


def build_page_viewer(config: Config | None = None):
    """The Page viewer components, to be called inside a `gr.Blocks`; returns `((heading, raw, cleaned, source), show, tabs)`.

    `show(page_file)` loads the viewer; the chat app calls it when a Page Link is chosen. The heading sits above
    `tabs` (Manual page, Markdown page); the caller can re-enter `tabs` to add its own tab.
    """
    heading = gr.HTML()
    with gr.Tabs() as tabs:  # tabs rather than columns: each gets the full width of the narrow right-hand side
        with gr.Tab("Manual page"):
            raw = gr.HTML()
        with gr.Tab("Markdown page"):
            source = gr.Textbox(visible=False)  # the .md file itself, which is what the button copies (State is invisible to js)
            copy = gr.Button("Kopieer markdown", size="sm")
            cleaned = gr.Markdown()
    copy.click(None, source, None, js=COPY_MARKDOWN_JS)

    def show(page_file: str | None):
        view = page_viewer(page_file, config)
        return view.heading, view.raw_html, view.cleaned_markdown, view.markdown_source

    return (heading, raw, cleaned, source), show, tabs


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
CHAT_ID = "chat"
TABS_ID = "chat-tabs"
FOCUS_NOW_JS = "() => document.querySelector('#" + QUESTION_ID + " textarea')?.focus()"
# Autofocus covers opening the app; this refocuses the question box when the browser tab is selected again.
FOCUS_QUESTION_JS = (
    "() => { const focus = () => document.querySelector('#" + QUESTION_ID + " textarea')?.focus();"
    " window.addEventListener('focus', focus); }"
)

LEFT_ID = "left"
# After an Answer the chat scrolls down, but stops when the latest question reaches the top of the chat
# (the browser clamps scrollTop, so a short Answer simply ends up at the bottom).
SCROLL_TO_QUESTION_JS = (
    "() => { setTimeout(() => {"
    " const chat = document.querySelector('#" + CHAT_ID + " .bubble-wrap');"
    " const rows = chat ? chat.querySelectorAll('.message-row.user-row') : [];"
    " const last = rows[rows.length - 1];"
    " if (last) chat.scrollTop += last.getBoundingClientRect().top - chat.getBoundingClientRect().top - 8;"
    " }, 50); }"
)
# Gradio puts a message's copy button below the message; this puts it to the right of the text, top-aligned.
# (20px is the message row's own top margin.)
CHAT_CSS = f"""
/* The question box stays at the bottom left: the left column fills the window and the chat takes what is left. */
#{LEFT_ID} {{ height: calc(100vh - 100px); min-height: 420px; }}
#{CHAT_ID} {{ height: auto !important; flex: 1 1 0 !important; min-height: 200px; }}
#{CHAT_ID} .message-wrap {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 4px; }}
#{CHAT_ID} .message-wrap > .message-row {{ grid-column: 1; }}
#{CHAT_ID} .message-wrap > .message-buttons {{ grid-column: 2; align-self: start; justify-self: start; margin: 20px 0 0 0; width: auto; }}
#{TABS_ID} {{ align-items: center; gap: 4px; flex-wrap: nowrap; }}
#{TABS_ID} > fieldset {{ flex: 0 1 auto !important; width: auto !important; min-width: 0 !important; }}
#{TABS_ID} fieldset .wrap {{ flex-wrap: nowrap; overflow-x: auto; }}
#{TABS_ID} input[type=radio] {{ display: none; }}  /* the Radio is shown as a row of tabs */
#{TABS_ID} label {{ border-radius: 6px 6px 0 0; }}
#{TABS_ID} label.selected {{ border-bottom: 2px solid var(--color-accent); font-weight: 600; }}
#{CHAT_ID} .message-buttons .icon-button-wrapper {{ margin: 0; }}  /* same size for user and assistant messages */
"""

DEBUG_HEADERS = ["chunk_id", "page title", "heading path", "score", "cited", "text"]
# One line per Chunk so all Retrieved Chunks fit; clicking a cell shows its full text (wrapped rows made the
# text column a one-word-wide strip and a single Chunk filled the table).
DEBUG_COLUMN_WIDTHS = ["20%", "14%", "16%", "7%", "7%", "36%"]
DEBUG_TABLE_HEIGHT = 600


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


@dataclass
class Conversation:
    """One chat tab: everything the left column and the Debug and Screenshots tabs show for it."""

    title: str = ""  # the first question; empty until there is one
    history: list = field(default_factory=list)
    shown: list = field(default_factory=list)  # accumulated Page Links, as (title, page_file)
    gallery: list = field(default_factory=list)
    large: object = field(default_factory=lambda: large_screenshot(None))
    rows: list = field(default_factory=list)
    notes: str = ""


TAB_TITLE_CHARS = 24


def chat_tabs(chats: list[Conversation], active: int):
    """The tab strip: one entry per conversation, named after its first question."""
    labels = []
    for number, chat in enumerate(chats, start=1):
        title = chat.title.strip()
        if len(title) > TAB_TITLE_CHARS:
            title = title[: TAB_TITLE_CHARS - 1].rstrip() + "…"
        labels.append((title or f"Chat {number}", number - 1))
    return gr.update(choices=labels, value=active)


def chat_view(chat: Conversation):
    """What to put in (chat, Page Links, gallery, large screenshot, Debug table, Debug notes) for a conversation."""
    links = gr.update(choices=chat.shown, value=None, visible=bool(chat.shown))
    return chat.history, links, chat.gallery, chat.large, chat.rows, chat.notes


def new_chat(chats: list[Conversation]):
    """The + button: add an empty conversation and switch to it."""
    chats = list(chats) + [Conversation()]
    active = len(chats) - 1
    return (chats, chat_tabs(chats, active), *chat_view(chats[active]))


def switch_chat(chats: list[Conversation], active: int):
    return chat_view(chats[active])


def submit(assistant, config: Config, message: str, chats: list[Conversation], active: int):
    """One turn in the active conversation: the `respond` outputs plus the updated conversations and tab strip."""
    chat = chats[active]
    history, box, links, gallery, large, rows, notes, shown = respond(
        assistant, config, message, chat.history, chat.shown
    )
    if message.strip():
        chat.history, chat.shown = history, shown
        chat.gallery, chat.large, chat.rows, chat.notes = gallery, large, rows, notes
        chat.title = chat.title or message.strip()
    return history, box, links, gallery, large, rows, notes, chats, chat_tabs(chats, active)


def clear_page_links(chats: list[Conversation], active: int):
    chats[active].shown = []
    return gr.update(choices=[], value=None, visible=False), chats


def keep_viewer_when_unselected(show):
    """Wrap the Page viewer's `show` so that clearing the radio (a new Answer) leaves the viewer as it is."""

    def wrapped(page_file: str | None):
        return show(page_file) if page_file else tuple(gr.update() for _ in range(VIEWER_OUTPUT_COUNT))

    return wrapped


def chat_blocks(assistant, config: Config) -> gr.Blocks:
    """Chat on the left, tabs (Manual page, Markdown page, Debug) on the right."""
    with gr.Blocks(title="Navigate Helper") as blocks:
        with gr.Row():
            with gr.Column(scale=2, elem_id=LEFT_ID):
                with gr.Row(elem_id=TABS_ID):
                    tab_strip = gr.Radio(
                        choices=[("Chat 1", 0)], value=0, show_label=False, container=False, scale=0, min_width=0,
                    )
                    plus = gr.Button("+", size="sm", scale=0, min_width=44)
                chat = gr.Chatbot(elem_id=CHAT_ID, autoscroll=False)
                links = gr.Radio(label="Page Links (kies om te openen)", visible=False)
                clear_links = gr.Button("Wis lijst", size="sm")
                box = gr.Textbox(placeholder="Stel een vraag", show_label=False, elem_id=QUESTION_ID, autofocus=True)
            with gr.Column(scale=3):
                viewer_outputs, show, tabs = build_page_viewer(config)
                with tabs, gr.Tab("Debug"):
                    table = gr.Dataframe(
                        headers=DEBUG_HEADERS, interactive=False, wrap=False, column_widths=DEBUG_COLUMN_WIDTHS,
                        max_height=DEBUG_TABLE_HEIGHT,
                    )
                    notes = gr.Markdown()
                with tabs, gr.Tab("Screenshots"):
                    gallery = gr.Gallery(label="Alle screenshots", columns=4, height=220, allow_preview=False)
                    large = gr.Image(label="Screenshot", interactive=False)
        chats = gr.State([Conversation()])
        view = [chat, links, gallery, large, table, notes]
        box.submit(
            lambda message, chats, active: submit(assistant, config, message, chats, active),
            [box, chats, tab_strip],
            [chat, box, links, gallery, large, table, notes, chats, tab_strip],
        ).then(None, None, None, js=SCROLL_TO_QUESTION_JS)
        plus.click(new_chat, chats, [chats, tab_strip, *view]).then(None, None, None, js=FOCUS_NOW_JS)
        tab_strip.input(switch_chat, [chats, tab_strip], view).then(None, None, None, js=FOCUS_NOW_JS)
        gallery.select(select_screenshot, None, large)
        clear_links.click(clear_page_links, [chats, tab_strip], [links, chats])
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
