"""The Code path as one service: a Manual Answer in, a Code Answer out (ADR 0001).

It knows nothing about the GUI. Progress is a plain stream of `ProgressEvent`s, and a run is stopped through a
`cancelled()` flag the caller owns; a stopped run still ends in a (partial) `CodeAnswer`.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator

from navigate_helper.ask import ManualAnswer
from navigate_helper.ask_log import AskLog
from navigate_helper.code_answer import CodeAnswer, CodeAnswerWriter
from navigate_helper.code_search import CodeSearch, ProgressEvent
from navigate_helper.code_tools import CodeTools
from navigate_helper.config import Config


class CodeChecker:
    """Checks a Manual Answer against the Code Checkout with the LLM chosen for this run."""

    def __init__(
        self, tools: CodeTools, code_date: str | None, *, allow_code_to_openai: bool = False, log: AskLog | None = None
    ):
        self._tools = tools
        self._code_date = code_date
        self._allow_code_to_openai = allow_code_to_openai
        self._log = log

    def check(
        self,
        manual: ManualAnswer,
        llm,
        cancelled: Callable[[], bool] = lambda: False,
        on_event: Callable[[ProgressEvent], None] | None = None,
    ) -> CodeAnswer:
        """Raises `CodeSearchError` when `llm` is not allowed to see code (OpenAI without approval)."""
        search = CodeSearch(llm, self._tools, allow_code_to_openai=self._allow_code_to_openai, log=self._log)
        writer = CodeAnswerWriter(
            llm, self._tools, self._code_date, allow_code_to_openai=self._allow_code_to_openai, log=self._log
        )
        # Only a real Manual Answer is handed over; "not covered" and error text are not claims to check.
        answered = manual.covered and manual.error is None
        manual_answer = manual.text if answered else None
        manual_pages = [page["page_file"] for page in manual.source_pages] if answered else []
        result = search.run(manual.question, manual_answer, manual_pages, cancelled, on_event)
        if result.status == "finished" and on_event is not None:
            on_event(ProgressEvent("writing", "Antwoord opstellen"))
        return writer.write(result, manual_answer, manual_pages)


def build_code_checker(config: Config) -> CodeChecker | None:
    """A checker over `CODE_DIR`, or None when it is not set or not a folder. Takes the "code per" date now, at startup."""
    if config.code_dir is None or not config.code_dir.is_dir():
        return None
    tools = CodeTools(config.code_dir)
    newest = tools.newest_modification()
    return CodeChecker(
        tools,
        newest.isoformat() if newest else None,
        allow_code_to_openai=config.allow_code_to_openai,
        log=AskLog(config.ask_log_path),
    )


def stream_check(
    checker: CodeChecker, manual: ManualAnswer, llm, cancelled: Callable[[], bool] = lambda: False
) -> Iterator[ProgressEvent | CodeAnswer]:
    """Run the check in a worker thread and yield its `ProgressEvent`s as they happen, then the `CodeAnswer`.

    An exception of the check (a refused provider) is raised here, in the caller's thread.
    """
    items: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            items.put(checker.check(manual, llm, cancelled, items.put))
        except Exception as error:
            items.put(error)

    threading.Thread(target=work, daemon=True).start()
    while True:
        item = items.get()
        if isinstance(item, Exception):
            raise item
        yield item
        if isinstance(item, CodeAnswer):
            return
