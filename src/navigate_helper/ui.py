"""The ui stage: the Gradio dev app. It knows only `Answer`; the rules are in docs/design-decisions.md,
section "Stages 4 and 5 – Gradio dev app"."""

import os
from dataclasses import dataclass, field

import gradio as gr
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from navigate_helper.ask import Answer, build_assistant
from navigate_helper.config import Config, load_config
from navigate_helper.page_view import FULL_PAGE_PREFIX, page_viewer, resolve_image, served_page


JUMP_ID = "page-jump"
# A link to another Manual Page, clicked inside the Manual page iframe, arrives as a message from that iframe;
# it is typed into the hidden `JUMP_ID` box, whose change event loads the page in the viewer.
PAGE_JUMP_JS = (
    "() => { window.addEventListener('message', (e) => {"
    " const page = e.data && e.data.navigateHelperPage;"
    " const ours = [...document.querySelectorAll('iframe')].some((f) => f.contentWindow === e.source);"
    " const box = document.querySelector('#" + JUMP_ID + " textarea');"
    " if (!page || !ours || !box) return;"
    " box.value = page; box.dispatchEvent(new Event('input', { bubbles: true })); }); }"
)
VIEWER_OUTPUT_COUNT = 4  # heading, raw page, Cleaned Page, Markdown source
# Copies the Markdown source and shows "Gekopieerd" on the clicked button for a moment.
COPY_MARKDOWN_JS = (
    "async (md) => { await navigator.clipboard.writeText(md || '');"
    " const button = document.activeElement;"
    " if (button) { const label = button.textContent; button.textContent = 'Gekopieerd ✓';"
    " setTimeout(() => { button.textContent = label; }, 1500); } }"
)


def build_page_viewer(config: Config | None = None, links: gr.Radio | None = None):
    """The Page viewer components, to be called inside a `gr.Blocks`; returns `((heading, raw, cleaned, source), show, tabs)`.

    `show(page_file)` loads the viewer; the chat app calls it when a Page Link is chosen. The heading sits above
    `tabs` (Manual page, Markdown page); the caller can re-enter `tabs` to add its own tab.
    A page opened from a link inside the Manual page clears `links`, so the page it was chosen from can be chosen again.
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
    jump = gr.Textbox(visible="hidden", elem_id=JUMP_ID)  # filled by PAGE_JUMP_JS, which the app passes to `launch(js=...)`

    def show(page_file: str | None):
        view = page_viewer(page_file, config)
        return view.heading, view.raw_html, view.cleaned_markdown, view.markdown_source


    def jump_to(page_file: str | None):
        """Load the page the iframe asked for, then empty the box so the same link works again."""
        if not page_file:
            return tuple(gr.update() for _ in range(VIEWER_OUTPUT_COUNT + 1 + (links is not None)))
        return (*show(page_file), "", *((gr.update(value=None),) if links is not None else ()))

    jump.change(jump_to, jump, [heading, raw, cleaned, source, jump, *([links] if links is not None else [])])
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
LINKS_ID = "page-links"
FOCUS_NOW_JS = "() => document.querySelector('#" + QUESTION_ID + " textarea')?.focus()"
# Autofocus covers opening the app; this refocuses the question box when the browser tab is selected again.
FOCUS_QUESTION_JS = (
    "() => { const focus = () => document.querySelector('#" + QUESTION_ID + " textarea')?.focus();"
    " window.addEventListener('focus', focus); }"
)

APP_JS = "() => { (" + FOCUS_QUESTION_JS + ")(); (" + PAGE_JUMP_JS + ")(); }"  # `launch(js=)` takes a single function

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
#{TABS_ID} {{ align-items: center; gap: 2px; flex-wrap: nowrap; overflow-x: auto; }}
#{LEFT_ID} > .column {{ flex: 0 0 auto !important; }}  /* the box gr.render draws the tab strip in must not take the chat's space */
#{TABS_ID} button {{ flex: 0 0 auto; white-space: nowrap; }}
#{TABS_ID} .chat-tab {{ gap: 0; flex: 0 0 auto; width: fit-content; min-width: 0; border-bottom: 2px solid transparent; }}
#{TABS_ID} .chat-tab.selected {{ border-bottom-color: var(--color-accent); }}
#{TABS_ID} .chat-tab.selected .chat-tab-title {{ font-weight: 600; }}
#{TABS_ID} .chat-tab-title, #{TABS_ID} .chat-tab-close {{ background: transparent; border: none; box-shadow: none; }}
#{TABS_ID} .chat-tab-close {{ padding: 0 6px; opacity: 0.6; }}
/* Page Links: at most three rows, then a scroll bar (a row is a 35px label, rows are 8px apart). */
#{LINKS_ID} > .wrap:not(.default) {{ max-height: calc(3 * 35px + 2 * 8px); overflow-y: auto; }}
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


def tab_labels(chats: list[Conversation]) -> list[str]:
    """One label per tab: the first question, cut to `TAB_TITLE_CHARS`, or "Chat N" until there is one."""
    labels = []
    for number, chat in enumerate(chats, start=1):
        title = chat.title.strip()
        if len(title) > TAB_TITLE_CHARS:
            title = title[: TAB_TITLE_CHARS - 1].rstrip() + "…"
        labels.append(title or f"Chat {number}")
    return labels


def chat_view(chat: Conversation):
    """What to put in (chat, Page Links, gallery, large screenshot, Debug table, Debug notes) for a conversation."""
    links = gr.update(choices=chat.shown, value=None, visible=bool(chat.shown))
    return chat.history, links, chat.gallery, chat.large, chat.rows, chat.notes


def new_chat(chats: list[Conversation]):
    """The + button: add an empty conversation and switch to it. Returns (chats, active, *chat_view)."""
    chats = list(chats) + [Conversation()]
    active = len(chats) - 1
    return (chats, active, *chat_view(chats[active]))


def close_chat(chats: list[Conversation], active: int, index: int):
    """The × on a tab: remove that conversation. Returns (chats, active, *chat_view).

    The active tab stays active unless it is the one closed; then the next one takes its place. The last
    conversation is never removed outright: it is replaced by an empty one.
    """
    chats = list(chats)
    del chats[index]
    if not chats:
        chats = [Conversation()]
    if index < active:
        active -= 1
    active = min(active, len(chats) - 1)
    return (chats, active, *chat_view(chats[active]))


def switch_chat(chats: list[Conversation], index: int):
    """A tab's title: returns (active, *chat_view)."""
    return (index, *chat_view(chats[index]))


def submit(assistant, config: Config, message: str, chats: list[Conversation], active: int, revision: int):
    """One turn in the active conversation: the `respond` outputs, the updated conversations and tab revision.

    The revision goes up when a tab gets its name (the first question), so the tab strip redraws.
    """
    chat = chats[active]
    history, box, links, gallery, large, rows, notes, shown = respond(
        assistant, config, message, chat.history, chat.shown
    )
    if message.strip():
        chat.history, chat.shown = history, shown
        chat.gallery, chat.large, chat.rows, chat.notes = gallery, large, rows, notes
        if not chat.title:
            chat.title = message.strip()
            revision += 1
    return history, box, links, gallery, large, rows, notes, chats, revision


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
        chats = gr.State([Conversation()])
        active = gr.State(0)
        revision = gr.State(0)  # bumped whenever the tab strip must be redrawn
        focus = dict(fn=None, inputs=None, outputs=None, js=FOCUS_NOW_JS)
        with gr.Row():
            with gr.Column(scale=2, elem_id=LEFT_ID):
                @gr.render(inputs=[chats, active], triggers=[blocks.load, revision.change])
                def draw_tabs(chats_now, active_now):
                    """The tab strip: a title and a × per conversation, and a + at the end."""
                    with gr.Row(elem_id=TABS_ID):
                        for index, label in enumerate(tab_labels(chats_now)):
                            selected = index == active_now
                            with gr.Row(elem_classes=["chat-tab", "selected" if selected else ""]):
                                title = gr.Button(label, size="sm", scale=0, min_width=0, elem_classes=["chat-tab-title"])
                                close = gr.Button("×", size="sm", scale=0, min_width=0, elem_classes=["chat-tab-close"])
                            title.click(
                                lambda chats, rev, index=index: (*switch_chat(chats, index), rev + 1),
                                [chats, revision], [active, *view, revision],
                            ).then(**focus)
                            close.click(
                                lambda chats, active, rev, index=index: (*close_chat(chats, active, index), rev + 1),
                                [chats, active, revision], [chats, active, *view, revision],
                            ).then(**focus)
                        plus = gr.Button("+", size="sm", scale=0, min_width=44)
                        plus.click(
                            lambda chats, rev: (*new_chat(chats), rev + 1),
                            [chats, revision], [chats, active, *view, revision],
                        ).then(**focus)
                chat = gr.Chatbot(elem_id=CHAT_ID, autoscroll=False)
                links = gr.Radio(label="Page Links (kies om te openen)", visible=False, elem_id=LINKS_ID)
                clear_links = gr.Button("Wis lijst", size="sm")
                box = gr.Textbox(placeholder="Stel een vraag", show_label=False, elem_id=QUESTION_ID, autofocus=True)
            with gr.Column(scale=3):
                viewer_outputs, show, tabs = build_page_viewer(config, links)
                with tabs, gr.Tab("Debug"):
                    table = gr.Dataframe(
                        headers=DEBUG_HEADERS, interactive=False, wrap=False, column_widths=DEBUG_COLUMN_WIDTHS,
                        max_height=DEBUG_TABLE_HEIGHT,
                    )
                    notes = gr.Markdown()
                with tabs, gr.Tab("Screenshots"):
                    gallery = gr.Gallery(label="Alle screenshots", columns=4, height=220, allow_preview=False)
                    large = gr.Image(label="Screenshot", interactive=False)
        view = [chat, links, gallery, large, table, notes]

        box.submit(
            lambda message, chats, active, rev: submit(assistant, config, message, chats, active, rev),
            [box, chats, active, revision],
            [chat, box, links, gallery, large, table, notes, chats, revision],
        ).then(None, None, None, js=SCROLL_TO_QUESTION_JS)
        gallery.select(select_screenshot, None, large)
        clear_links.click(clear_page_links, [chats, active], [links, chats])
        links.change(keep_viewer_when_unselected(show), links, list(viewer_outputs))
    return blocks


def manual_app(config: Config) -> FastAPI:
    """The route behind **open full page**: a Manual Page at `/manual/<Page>.htm`, so its links to other pages work."""
    app = FastAPI()

    @app.get(FULL_PAGE_PREFIX + "{name}")
    def manual_page(name: str):
        page = served_page(name, config)
        if page is None:
            raise HTTPException(status_code=404, detail="Pagina niet gevonden")
        return HTMLResponse(page, headers={"Content-Security-Policy": "script-src 'none'"})

    return app


def serve(blocks: gr.Blocks, config: Config, **launch_args) -> None:
    """Run `blocks` plus the full-page route on one port (GRADIO_SERVER_PORT, default 7860).

    Listens on 127.0.0.1 (this machine only) unless GRADIO_SERVER_NAME says otherwise, e.g. 0.0.0.0 for the company network.
    """
    app = gr.mount_gradio_app(manual_app(config), blocks, path="/", allowed_paths=[str(config.raw_dir.resolve())], **launch_args)
    uvicorn.run(app, host=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"), port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")))


def run(config: Config) -> None:
    assistant = build_assistant(config)  # once, at startup (slow: loads the e5 model)
    serve(chat_blocks(assistant, config), config, js=APP_JS, css=CHAT_CSS)


if __name__ == "__main__":
    _config = load_config()
    serve(page_viewer_blocks(_config), _config, js=PAGE_JUMP_JS)
