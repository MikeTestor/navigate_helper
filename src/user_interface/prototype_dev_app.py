"""PROTOTYPE (throwaway, wayfinder ticket #12): Gradio dev app layout with a FAKE Answer.

Question: how should the dev app look and behave (layout, Page Links, page viewer,
Screenshots gallery, debug panel)?

Run:  uv run --with "gradio>=6.27" python src/user_interface/prototype_dev_app.py
Two layout variants, switched with the radio at the top:
  A  chat left, right-hand tabs (Page viewer | Debug)             [seed recommendation]
  B  chat left, Debug and Page viewer stacked underneath the chat, full-width viewer
"""

import html
import re
from pathlib import Path

import gradio as gr

DATA = Path(r"C:\Aryza_navigate_Kennispagina\Data")  # raw Manual pages + images

# ---- fake Answer -------------------------------------------------------------
FAKE = {
    "text": "Een budget leg je vast via **Budgetten** ... (fake antwoord, bronnen: [Budgetten#3], [Budgetten#5]).",
    "covered": True,
    "page_links": ["Budgetten.htm", "Acties,_Kostenmoderatie_kostenstempel.htm", "Partner_vastleggen_en_wijziging_huwelijksgoederenrecht.htm"],
    "chunks": [  # chunk_id, page, heading path, score, cited, text
        ["Budgetten#3", "Budgetten.htm", "Budgetten > Vastleggen", 0.91, True, "Kies Nieuw budget en vul ..."],
        ["Budgetten#5", "Budgetten.htm", "Budgetten > Verdelen", 0.88, True, "Het budget wordt verdeeld ..."],
        ["Acties,_Kostenmoderatie_kostenstempel#1", "Acties,_Kostenmoderatie_kostenstempel.htm", "Kostenmoderatie", 0.83, False, "Kostenstempel ..."],
        ["Partner_vastleggen#2", "Partner_vastleggen_en_wijziging_huwelijksgoederenrecht.htm", "Partner", 0.79, False, "Huwelijksgoederenrecht ..."],
    ],
}


def title_of(name: str) -> str:
    return name.removesuffix(".htm").replace("_", " ")


def screenshots(pages: list[str]) -> list[tuple[str, str]]:
    out, seen = [], set()
    for p in pages[:2]:
        raw = (DATA / p).read_text(encoding="utf-8-sig", errors="ignore")
        for src in re.findall(r'<img[^>]+src="([^"]+)"', raw):
            f = DATA / src
            if f.exists() and src not in seen and len(out) < 6:
                seen.add(src)
                out.append((str(f), f"{title_of(p)} / {src}"))
    return out


def raw_iframe(name: str, height: int = 520) -> str:
    """Raw page: strip scripts, images -> Gradio file URLs, srcdoc iframe, sandbox allow-same-origin."""
    raw = (DATA / name).read_text(encoding="utf-8-sig", errors="ignore")
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
    raw = re.sub(
        r'(<img[^>]+src=")([^"]+)"',
        lambda m: f'{m.group(1)}/gradio_api/file={(DATA / m.group(2)).as_posix()}"',
        raw,
    )
    return (
        f'<iframe sandbox="allow-same-origin" srcdoc="{html.escape(raw)}" '
        f'style="width:100%;height:{height}px;border:1px solid #ccc"></iframe>'
    )


def cleaned_stub(name: str) -> str:
    return f"# {title_of(name)}\n\n*(prototype: the Cleaned Page Markdown would render here)*\n\n" + "\n\n".join(
        c[5] for c in FAKE["chunks"] if c[1] == name
    )


def open_link(name: str | None):
    if not name:
        return gr.update(), gr.update(), gr.update()
    full = f"[open full page](/gradio_api/file={(DATA / name).as_posix()})"
    return raw_iframe(name), cleaned_stub(name), f"**{title_of(name)}** · {full} · shared-drive path: `{DATA / name}`"


def ask(message: str, history: list[dict]):
    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": FAKE["text"]}]
    pages = FAKE["page_links"]
    rows = [[c[0], title_of(c[1]), c[2], c[3], "ja" if c[4] else "", c[5]] for c in FAKE["chunks"]]
    return (
        history,
        "",
        gr.update(choices=[(title_of(p), p) for p in pages], value=None, visible=True),
        screenshots(pages),
        rows,
    )


# ---- layout ------------------------------------------------------------------
with gr.Blocks(title="PROTOTYPE dev app") as demo:
    variant = gr.Radio(["A", "B"], value="A", label="PROTOTYPE layout variant")

    def viewer_widgets():
        with gr.Row():
            raw_html = gr.HTML("<i>Kies een Page Link</i>", label="Manual Page (raw)")
            cleaned = gr.Markdown("*Cleaned Page*")
        return raw_html, cleaned

    def debug_widgets():
        return gr.Dataframe(
            headers=["chunk_id", "page", "heading path", "score", "cited", "text"],
            interactive=False,
            wrap=True,
        )

    with gr.Column(visible=True) as col_a:
        with gr.Row():
            with gr.Column(scale=2):
                chat_a = gr.Chatbot(height=420)
                links_a = gr.Radio(label="Page Links (kies om te openen)", visible=False)
                gallery_a = gr.Gallery(label="Screenshots", columns=3, height=200)
                msg_a = gr.Textbox(placeholder="Stel een vraag", show_label=False)
            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("Page viewer"):
                        info_a = gr.Markdown("")
                        raw_a, clean_a = viewer_widgets()
                    with gr.Tab("Debug"):
                        debug_a = debug_widgets()

    with gr.Column(visible=False) as col_b:
        chat_b = gr.Chatbot(height=300)
        msg_b = gr.Textbox(placeholder="Stel een vraag", show_label=False)
        with gr.Row():
            links_b = gr.Dropdown(label="Page Links", visible=False)
            gallery_b = gr.Gallery(label="Screenshots", columns=6, height=140)
        info_b = gr.Markdown("")
        raw_b, clean_b = viewer_widgets()
        with gr.Accordion("Debug: Retrieved Chunks", open=False):
            debug_b = debug_widgets()

    variant.change(lambda v: (gr.update(visible=v == "A"), gr.update(visible=v == "B")), variant, [col_a, col_b])

    msg_a.submit(ask, [msg_a, chat_a], [chat_a, msg_a, links_a, gallery_a, debug_a])
    links_a.input(open_link, links_a, [raw_a, clean_a, info_a])
    msg_b.submit(ask, [msg_b, chat_b], [chat_b, msg_b, links_b, gallery_b, debug_b])
    links_b.input(open_link, links_b, [raw_b, clean_b, info_b])

if __name__ == "__main__":
    demo.launch(allowed_paths=[str(DATA)])
