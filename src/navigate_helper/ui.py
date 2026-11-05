"""The ui stage: the Gradio dev app. It knows only `ManualAnswer`; the rules are in docs/design-decisions.md,
section "Stages 4 and 5 – Gradio dev app"."""

import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import gradio as gr
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from navigate_helper.ask import ManualAnswer, build_assistant
from navigate_helper.code_answer import CodeAnswer, format_citations, format_code_answer
from navigate_helper.code_check import CodeChecker, build_code_checker, stream_check
from navigate_helper.config import DEFAULT_LLM_MODELS, PROVIDERS, Config, allowed_models, load_config
from navigate_helper.llm import LLMSwitch
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


def answer_view(answer: ManualAnswer, config: Config) -> AnswerView:
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
    if answer.provider:
        notes.append(f"**model:** {answer.provider} / {answer.model}")
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


CHECK_OPTION = "controleer-in-de-code"
CHECK_LABEL = "Controleer in de code"


def code_option() -> list[dict]:
    """The button under a Manual Answer: Gradio shows a message's options under the latest message of the chat."""
    return [{"label": CHECK_LABEL, "value": CHECK_OPTION}]


def respond(assistant, config: Config, message: str, history: list[dict], shown=(), pick=None, offer_code=False):
    """One chat turn: returns (history, textbox, page link radio, gallery, large screenshot, debug rows, debug notes,
    shown links).

    `pick()` returns the LLM chosen in the provider and model dropdowns for this question; a refused or unavailable
    choice (no API key) is reported in the chat like any other error. `offer_code` puts the "check against the code"
    button under the Answer.
    """
    return respond_with_answer(assistant, config, message, history, shown, pick, offer_code)[0]


def respond_with_answer(assistant, config: Config, message: str, history: list[dict], shown=(), pick=None, offer_code=False):
    """`respond`, plus the `ManualAnswer` it showed (None for a blank or failed question): `(outputs, answer)`."""
    shown = list(shown)
    if not message.strip():
        return (history, message, *(gr.update() for _ in range(5)), shown), None
    first_question = not history
    history = history + [{"role": "user", "content": message}]
    try:
        answer = assistant.ask(message, llm=pick() if pick else None)
    except Exception as error:  # retrieval and config errors raise from ask, and from an unavailable choice
        history.append({"role": "assistant", "content": f"Er ging iets mis: {type(error).__name__}: {error}"})
        return (history, "", gr.update(), [], large_screenshot(None), [], f"**error:** {error}", shown), None
    view = answer_view(answer, config)
    history.append({"role": "assistant", "content": answer.text, **({"options": code_option()} if offer_code else {})})
    shown = merge_page_links(shown, view.page_link_choices)
    radio = {"choices": shown, "visible": bool(shown)}
    if first_question and view.page_link_choices:
        # Only the first Answer preselects a page (which loads the viewer); later Answers leave the viewer alone.
        radio["value"] = view.page_link_choices[0][1]
    first_shot = view.gallery[0] if view.gallery else None  # section 2 of the Screenshots tab starts on the first
    outputs = (
        history, "", gr.update(**radio), view.gallery, large_screenshot(first_shot), view.debug_rows, view.debug_notes,
        shown,
    )
    return outputs, answer


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
    # The Code path: the latest Manual Answer (what the check button checks), whether the check starts by itself,
    # the Code Citation view, and the run in progress (`stop` is set by the Stop button).
    last_manual: ManualAnswer | None = None
    auto_check: bool = False
    code_view: str = ""
    checking: bool = False
    stop: threading.Event | None = None


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
    """What to put in (chat, Page Links, gallery, large screenshot, Debug table, Debug notes, Code view) for a conversation."""
    links = gr.update(choices=chat.shown, value=None, visible=bool(chat.shown))
    return chat.history, links, chat.gallery, chat.large, chat.rows, chat.notes, chat.code_view


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


def submit(
    assistant, config: Config, message: str, chats: list[Conversation], active: int, revision: int, pick=None,
    offer_code=False,
):
    """One turn in the active conversation: the `respond` outputs, the updated conversations and tab revision.

    The revision goes up when a tab gets its name (the first question), so the tab strip redraws. With `offer_code`
    (there is a Code Checkout) a Manual Answer that says "not in the Manual" starts the Code check by itself.
    """
    chat = chats[active]
    (history, box, links, gallery, large, rows, notes, shown), answer = respond_with_answer(
        assistant, config, message, chat.history, chat.shown, pick, offer_code
    )
    if message.strip():
        chat.history, chat.shown = history, shown
        chat.gallery, chat.large, chat.rows, chat.notes = gallery, large, rows, notes
        if answer is not None:
            chat.last_manual = answer
            chat.auto_check = offer_code and not answer.covered and answer.error is None
        if not chat.title:
            chat.title = message.strip()
            revision += 1
    return history, box, links, gallery, large, rows, notes, chats, revision


def clear_page_links(chats: list[Conversation], active: int):
    chats[active].shown = []
    return gr.update(choices=[], value=None, visible=False), chats


PROGRESS_TITLE = "Code-onderzoek"


def busy(chats: list[Conversation]) -> bool:
    """A Code check is running: the tab strip is frozen, because its updates would land in the wrong conversation."""
    return any(chat.checking for chat in chats)


def without_options(message: dict) -> dict:
    return {key: value for key, value in message.items() if key != "options"}


def check_code(chat: Conversation, checker: CodeChecker | None, pick) -> Iterator[None]:
    """Check the conversation's latest Manual Answer against the code, updating `chat` in place.

    Yields after every change (progress line, answer) so the caller can redraw. The history gets a collapsible
    progress block (the tool calls, as they happen) and then the labelled Code Answer below the Manual Answer; the
    citations go to `chat.code_view`. A refused provider or unavailable choice ends as a chat message with the button
    back. Stop (`chat.stop`) ends the search early with a partial Code Answer.
    """
    manual = chat.last_manual
    if checker is None or manual is None or chat.checking:
        return
    chat.checking, chat.stop, chat.auto_check = True, threading.Event(), False
    progress = {"role": "assistant", "content": "", "metadata": {"title": PROGRESS_TITLE, "status": "pending"}}
    chat.history = [without_options(m) for m in chat.history] + [progress]
    lines: list[str] = []
    answer: CodeAnswer | None = None
    yield
    try:
        for item in stream_check(checker, manual, pick(), chat.stop.is_set):
            if isinstance(item, CodeAnswer):
                answer = item
                continue
            lines.append(item.text)
            progress["content"] = "\n".join(f"- {line}" for line in lines)
            yield
    except Exception as error:  # a refused provider (OpenAI without approval), no API key, a crashed run
        chat.history = [m for m in chat.history if m is not progress or lines]
        if lines:
            progress["metadata"]["status"] = "done"
        message = f"Het code-onderzoek is niet gelukt: {type(error).__name__}: {error}"
        chat.history = chat.history + [{"role": "assistant", "content": message, "options": code_option()}]
    else:
        steps = sum(1 for line in lines if line != "Onderzoek gestart" and line != "Antwoord opstellen")
        progress["metadata"] = {"title": f"{PROGRESS_TITLE}: {steps} {'stap' if steps == 1 else 'stappen'}", "status": "done"}
        chat.history = chat.history + [{"role": "assistant", "content": format_code_answer(answer, snippets=False)}]
        chat.code_view = format_citations(answer)
    finally:
        chat.checking, chat.stop = False, None
    yield


def stop_check(chats: list[Conversation], active: int) -> None:
    """The Stop button: ask the running search to end; it still finishes with a partial Code Answer."""
    stop = chats[active].stop
    if stop is not None:
        stop.set()


def code_outputs(chat: Conversation, chats: list[Conversation]):
    """(chat, question box, Stop button, Code view, chats) after a step of a Code check."""
    return (
        chat.history, gr.update(interactive=not chat.checking), gr.update(visible=chat.checking), chat.code_view, chats,
    )


def run_check(checker, switch: LLMSwitch, chats: list[Conversation], active: int, provider: str, model: str):
    """The Gradio handler of the check button: `check_code` for the active conversation, one output set per step."""
    chat = chats[active]
    yielded = False
    for _ in check_code(chat, checker, lambda: switch.get(provider, model)):
        yielded = True
        yield code_outputs(chat, chats)
    if not yielded:  # nothing to check: leave the page as it is
        yield (gr.update(), gr.update(), gr.update(), gr.update(), chats)


def auto_check(checker, switch: LLMSwitch, chats: list[Conversation], active: int, provider: str, model: str):
    """Runs after every question: the check starts by itself only when the Manual Answer was "not covered"."""
    if chats[active].auto_check:
        yield from run_check(checker, switch, chats, active, provider, model)
    else:
        yield (gr.update(), gr.update(), gr.update(), gr.update(), chats)


def keep_viewer_when_unselected(show):
    """Wrap the Page viewer's `show` so that clearing the radio (a new Answer) leaves the viewer as it is."""

    def wrapped(page_file: str | None):
        return show(page_file) if page_file else tuple(gr.update() for _ in range(VIEWER_OUTPUT_COUNT))

    return wrapped


def models_for(config: Config, provider: str):
    """The model dropdown for a provider: its allowlist, with the `.env` model (default provider) or the first selected."""
    value = config.llm_model if provider == config.llm_provider else DEFAULT_LLM_MODELS[provider]
    return gr.update(choices=list(allowed_models(config, provider)), value=value)


def chat_blocks(
    assistant, config: Config, switch: LLMSwitch | None = None, checker: CodeChecker | None = None
) -> gr.Blocks:
    """Chat on the left, tabs (Manual page, Markdown page, Debug, Screenshots, and Code) on the right.

    `switch` builds the adapter for the provider and model chosen in the dropdowns; by default it starts from
    the assistant's own LLM. With a `checker` (there is a Code Checkout) every Manual Answer gets the "check against
    the code" button, and the Code tab and the Stop button appear; without one the app is as it was.
    """
    switch = switch or LLMSwitch(config, seed=getattr(assistant, "llm", None))
    skip_tab = lambda count: tuple(gr.update() for _ in range(count))  # noqa: E731  a tab click while a check runs
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
                                lambda chats, rev, index=index: (
                                    skip_tab(len(view) + 2) if busy(chats) else (*switch_chat(chats, index), rev + 1)
                                ),
                                [chats, revision], [active, *view, revision],
                            ).then(**focus)
                            close.click(
                                lambda chats, active, rev, index=index: (
                                    skip_tab(len(view) + 3) if busy(chats) else (*close_chat(chats, active, index), rev + 1)
                                ),
                                [chats, active, revision], [chats, active, *view, revision],
                            ).then(**focus)
                        plus = gr.Button("+", size="sm", scale=0, min_width=44)
                        plus.click(
                            lambda chats, rev: skip_tab(len(view) + 3) if busy(chats) else (*new_chat(chats), rev + 1),
                            [chats, revision], [chats, active, *view, revision],
                        ).then(**focus)
                chat = gr.Chatbot(elem_id=CHAT_ID, autoscroll=False)
                links = gr.Radio(label="Page Links (kies om te openen)", visible=False, elem_id=LINKS_ID)
                clear_links = gr.Button("Wis lijst", size="sm")
                with gr.Row():
                    provider = gr.Dropdown(
                        choices=list(PROVIDERS), value=config.llm_provider, label="Provider", allow_custom_value=False
                    )
                    model = gr.Dropdown(
                        choices=list(allowed_models(config, config.llm_provider)), value=config.llm_model,
                        label="Model", allow_custom_value=False,
                    )
                stop = gr.Button("Stop", visible=False, variant="stop", size="sm") if checker else None
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
                if checker:
                    with tabs, gr.Tab("Code"):
                        code_view = gr.Markdown()
                else:
                    code_view = gr.Markdown(visible=False)  # keeps `view` the same shape; there is nothing to show
        view = [chat, links, gallery, large, table, notes, code_view]

        provider.change(lambda name: models_for(config, name), provider, model)
        asked = box.submit(
            lambda message, name, choice, chats, active, rev: submit(
                assistant, config, message, chats, active, rev, pick=lambda: switch.get(name, choice),
                offer_code=checker is not None,
            ),
            [box, provider, model, chats, active, revision],
            [chat, box, links, gallery, large, table, notes, chats, revision],
        )
        asked.then(None, None, None, js=SCROLL_TO_QUESTION_JS)
        if checker:
            check_inputs = [provider, model, chats, active]
            check_outputs = [chat, box, stop, code_view, chats]

            # Real generator functions, not lambdas returning one: Gradio only streams a function that is a generator.
            def check_after_question(name, choice, chats, active):
                yield from auto_check(checker, switch, chats, active, name, choice)

            def check_on_click(name, choice, chats, active):
                yield from run_check(checker, switch, chats, active, name, choice)

            asked.then(check_after_question, check_inputs, check_outputs).then(None, None, None, js=SCROLL_TO_QUESTION_JS)
            chat.option_select(check_on_click, check_inputs, check_outputs).then(None, None, None, js=SCROLL_TO_QUESTION_JS)
            stop.click(stop_check, [chats, active], None, queue=False)
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
    checker = build_code_checker(config)  # None without CODE_DIR; the "code per" date is taken here, at startup
    serve(chat_blocks(assistant, config, checker=checker), config, js=APP_JS, css=CHAT_CSS)


if __name__ == "__main__":
    _config = load_config()
    serve(page_viewer_blocks(_config), _config, js=PAGE_JUMP_JS)
