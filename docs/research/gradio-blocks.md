# Gradio Blocks for Page Links, iframes, file URLs and galleries (2026-09-28)

Research for [#7](https://github.com/MikeTestor/navigate_helper/issues/7), feeding open questions F23–F27 in [open-questions.md](../open-questions.md). Terminology is defined in [CONTEXT.md](../../CONTEXT.md).

**Versions.** The project pins `gradio>=6.27.0`; `uv.lock` has **6.27.0** (released 2026-09-11). The latest on PyPI is **6.28.0** (2026-09-18). Facts below come from the 6.27.0 source (installed in a scratch venv), the gradio.app docs, and a throwaway probe app run in a Chromium 152 browser. "Verified" means seen in that probe.

## 1. A clickable Page Link list that loads a viewer

Four built-in ways, all verified in 6.27.0:

| Mechanism | How it works | What the handler gets |
|---|---|---|
| **Chatbot message `options`** | An assistant message dict can carry `"options": [{"label": ..., "value": ...}]`. They show as buttons under that message and stay in the history. `chatbot.option_select(fn, ...)` fires on click. | `gr.SelectData`: `index` and `value` (verified: `value='Mappen.htm'`) |
| **`gr.Dataset`** under the chat | Return `gr.Dataset(samples=[[title, file], ...])` from the answer handler; `layout="table"` with `headers`. `.click` / `.select`. | `type="values"` gives the row; `"index"` gives its position; `"tuple"` gives both |
| **`gr.Radio` / `gr.Dropdown`** | Return `gr.Radio(choices=[(label, value), ...], value=None)` per Answer. `.change` / `.input` / `.select`. | the chosen value |
| **`chatbot.select`** | Fires on a click on a message. | `index` and the message's `value` (the whole Markdown text), so not per link |

- Chatbot events in 6.27.0: `change, select, like, retry, undo, example_select, option_select, clear, copy, edit` ([source `chatbot.py`](https://github.com/gradio-app/gradio/blob/main/gradio/components/chatbot.py), [docs](https://www.gradio.app/docs/gradio/chatbot)). Dataset events: `change, click, select` ([docs](https://www.gradio.app/docs/gradio/dataset)). Radio: `select, change, input`. Dropdown: `change, input, select, focus, blur, key_up`.
- **Markdown links inside a chat message** are rendered as `<a target="_blank" rel="noopener noreferrer" href="Budgetten.htm">` (verified). A relative `.htm` href resolves against the Gradio server, so it opens `http://127.0.0.1:7860/Budgetten.htm` → `{"detail":"Not Found"}` (verified). No Gradio event fires. This is why F24 option 1 exists.
- Message content can also be a Gradio component (`gr.HTML`, `gr.Gallery`, `gr.Image`, …) ([docs](https://www.gradio.app/docs/gradio/chatbot)). `gr.HTML` can send custom events from JavaScript with `trigger('click', {...})` in `js_on_load`; the handler reads them from `gr.EventData` ([source `html.py`](https://github.com/gradio-app/gradio/blob/main/gradio/components/html.py)). 6.28.0 lets `gr.HTML` trigger any event name ([CHANGELOG](https://github.com/gradio-app/gradio/blob/main/gradio/CHANGELOG.md), #12967). This is the "inline links plus custom JS" route (F24 option 2).

## 2. A sandboxed `<iframe srcdoc>` inside `gr.HTML`

- **`gr.HTML` is not sanitised.** The 6.27.0 source says it "renders its content via the DOM's `innerHTML`, which does not execute `<script>` tags" (`html.py`), and it warns if it finds a `<script>` tag. An `<iframe sandbox="" srcdoc="...">` passed as its value reached the DOM intact (verified: `sandbox` and `srcdoc` attributes present, document rendered, its `<style>` applied).
- By contrast, `gr.Markdown` and `gr.Chatbot` sanitise by default (`sanitize_html=True`), in the browser with amuchina. 6.28.0 also strips `<style>` and `<link>` elements there ([PR #13662](https://github.com/gradio-app/gradio/pull/13662), merged 2026-07-29). That doesn't affect `gr.HTML`.
- **srcdoc rules (MDN).** The document's location is `about:srcdoc`, and **relative URLs resolve against the embedding page's URL**. An empty `sandbox` applies all restrictions. `allow-same-origin` without `allow-scripts` lets the parent read the frame's DOM but runs no scripts. Using `allow-scripts` together with `allow-same-origin` "is strongly discouraged" because the framed page can then remove its own sandbox ([MDN `<iframe>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)).
- **Images in a fully sandboxed srcdoc did not load** (verified in Chromium 152). With `sandbox=""` (opaque `null` origin), `<img src="/gradio_api/file=...">` showed as broken. Relative URL, absolute `http://127.0.0.1:…` URL, and `allow="local-network-access"` all failed, and the browser made no request at all. A `data:` URI image did load. With `sandbox="allow-same-origin"` or no sandbox, the same image loaded. The likely cause, not confirmed, is Chrome's Local Network Access: it blocks requests to loopback addresses from a `null` origin in Chrome 142 and later ([Chrome blog](https://developer.chrome.com/blog/local-network-access), [MDN `loopback-network`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy/loopback-network)).
- The browser blocks scripts in a sandboxed srcdoc ("Blocked script execution in 'about:srcdoc'…"). Links inside it, such as `other.htm`, resolve against the Gradio server.

Options for the raw-page viewer (F25):

1. `sandbox="allow-same-origin"` without `allow-scripts`, plus stripped scripts and image `src` rewritten to `/gradio_api/file=…`. Verified to render images.
2. `sandbox=""` with images inlined as `data:` URIs. Fully isolated, but a large page carries all of its images.
3. No iframe: inject the stripped page straight into `gr.HTML`. The page's own CSS then leaks into the app, because only `css_template` is scoped.
4. `<iframe src="/gradio_api/file=<raw page>.htm">`: the raw `.htm` would be served from `allowed_paths`, and its relative image paths would resolve against its own location. Not tested. Bare-filename images live in `raw/images/`, not next to the page, so this only covers some pages.

## 3. `allowed_paths`, `gr.set_static_paths` and `/gradio_api/file=`

- The URL form is `http://<app>/gradio_api/file=<local-file-path>` ([File access guide](https://www.gradio.app/guides/file-access)). Absolute Windows paths with forward slashes work, e.g. `/gradio_api/file=C:/…/raw/images/image1.jpg` → 200, `image/jpeg`, `Content-Disposition: inline` (verified).
- A file outside `allowed_paths`, the cwd and the temp and cache folders returns **403** `{"detail":"File not allowed: …"}` (verified). `blocked_paths` takes precedence over what Gradio exposes by default (guide).
- **`launch(allowed_paths=[...])`** allows those folders. When a component value (for example a Gallery item) points at such a file, Gradio **copies it into its cache** (`%TEMP%\gradio\<hash>\image1.jpg`) and serves the copy. Verified: the Gallery `src` pointed at the cache copy.
- **`gr.set_static_paths([...])`** serves files "directly from the file system instead of being copied", inline. It applies to all apps in the interpreter session, and "ALL files in that directory will be accessible over the network" (source `utils.py`). This suits `raw/images/`, which doesn't change while the app runs.
- A hand-written `<img src="/gradio_api/file=…">` in `gr.HTML` or Markdown is not copied. It only needs the path to be allowed (verified via `allowed_paths`).
- Dotfiles in the cwd are never moved to the cache (guide). The guide says nothing about UNC or network-share paths.

## 4. `gr.Gallery`

- Value: a list of paths, URLs, PIL or numpy images, or `(media, caption)` tuples ([docs](https://www.gradio.app/docs/gradio/gallery), source `gallery.py`). Captions show on the thumbnails and under the enlarged image (verified).
- **No deduplication.** Passing the same file twice shows two tiles (verified). Duplicates have to be removed before the value is returned.
- **Click to enlarge**: `allow_preview=True` (the default) opens a preview inside the component. It has the enlarged image, its caption, a thumbnail strip, and download, fullscreen, share and close buttons (verified). `buttons` defaults to `["share", "download", "download_all", "fullscreen"]`. Other options: `preview=True` starts in preview mode; `selected_index`, `columns` (default 2), `rows`, `height`, `object_fit`.
- Events: `select` (SelectData, index plus value), `change`, `upload`, `delete`, `preview_open`, `preview_close`. 6.28.0 added "Download All" (#13566).

## 5. `file://` links to the shared drive from `http://localhost`

- **Chrome and Edge block it.** For security reasons, Chrome forbids navigating to `file://` URLs from non-`file://` pages. The click silently does nothing, and the console shows `Not allowed to load local resource`. The main reason is that SMB fetches can leak the user's name and password hash. No user setting turns this off in Chrome or Edge 76+ (Eric Lawrence, [Restrictions on File Urls](https://textslashplain.com/2019/10/09/navigating-to-file-urls/), updated 2026-06-08). Verified: clicking `<a href="file:///C:/…/test.htm" target="_blank">` in `gr.HTML` did nothing (no new tab, no navigation). `gr.Markdown` keeps `file://` hrefs, rendering them with `target="_blank"`, but Chromium's block applies the same way.
- **Edge policy `IntranetFileLinksEnabled`** (Windows, Edge 95+) only applies to links "from intranet zone HTTPS websites". Even then it opens **Windows Explorer** at the file rather than the page. Also, "https://localhost/ is blocked as an exception … while loopback addresses (127.0.0.\*, [::1]) are considered internet zone" ([Microsoft Learn](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/intranetfilelinksenabled), 2026-05-20). So it doesn't help a localhost Gradio app.
- Other workarounds in the same post: IE mode, a "local file links" browser extension, and `--allow-file-access-from-files`, which covers XHR and fetch only.
- **What does work from Gradio:** serve the shared-drive folder over HTTP with `allowed_paths` or `gr.set_static_paths`, and link to `/gradio_api/file=C:/Aryza_navigate_Kennispagina/Data/<page>.htm`. That page then loads its relative CSS and images from the same folder over HTTP (not tested). Other options: show the `file://` path as copyable text, or a "copy path" button.

## Implications for the Gradio dev app

- **F23 (layout):** `gr.Blocks` supports everything above. `gr.ChatInterface` isn't needed for any of it.
- **F24 (Page Link → viewer):** Chatbot message `options` + `option_select` gives per-Answer buttons that stay under each message in the history, with no extra component. A `gr.Dataset`, `gr.Radio` or `gr.Dropdown` below the chat also works, but only shows the latest Answer's links. Plain Markdown `.htm` links in the chat open a 404 tab unless they are removed or rewritten.
- **F25 (raw page):** `gr.HTML` keeps an `<iframe srcdoc>`. Screenshots inside it load with `sandbox="allow-same-origin"` (no `allow-scripts`), but not with a bare `sandbox=""` in current Chromium, unless the images are inlined as `data:` URIs.
- **F26 (Screenshots):** `gr.Gallery` with `(path, caption)` tuples gives captions and click-to-enlarge. The app must remove duplicates itself. `gr.set_static_paths(raw/images)` avoids copying about 4,700 images into the cache. `allowed_paths` copies each image into the cache the first time it's shown.
- **Shared drive:** direct `file://` links won't open from a localhost page in Chrome or Edge. Serving the Kennispagina folder through Gradio, or showing a copyable path, are the options.
