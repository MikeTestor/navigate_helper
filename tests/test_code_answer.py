"""The Code Answer contract: structuring a Code Search conclusion, validating citations against the Code Checkout.

Everything runs on `tmp_path` and fakes: no real LLM, no real Code Checkout.
"""

import json

import pytest

from navigate_helper.ask_log import AskLog
from navigate_helper.code_answer import (
    ALWAYS_NOT_CHECKED,
    CodeAnswer,
    CodeAnswerWriter,
    LLMCodeAnswer,
    LLMCodeCitation,
    format_code_answer,
)
from navigate_helper.code_search import CodeSearchError, CodeSearchResult, ToolCallRecord
from navigate_helper.code_tools import CodeTools
from navigate_helper.llm import LLMError
from tests.fakes import FakeLLM

CONCLUSION = "De code controleert de factuur in src/order.p:2-3."
PAGES = ["Facturen.htm", "Betalingen.htm"]
EVIDENCE = [ToolCallRecord("grep", {"pattern": "Invoice"}, True, 120), ToolCallRecord("read", {"path": "src/order.p"}, True, 800)]


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "code"
    (root / "src").mkdir(parents=True)
    (root / "src" / "order.p").write_text("".join(f"order line {n}\n" for n in range(1, 31)), encoding="utf-8")
    (root / "src" / "big.p").write_text("".join(f"big line {n}\n" for n in range(1, 51)), encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "secret.p").write_text("Invoice secret\n", encoding="utf-8")
    return CodeTools(root)


def finished(conclusion=CONCLUSION, **overrides):
    return CodeSearchResult("Hoe werkt facturen?", "finished", conclusion, tool_calls=list(EVIDENCE), provider="p", model="m", **overrides)


def structured(citations=(("src/order.p", 2, 3),), **overrides):
    fields = dict(
        answer="De code controleert de factuur.",
        citations=[LLMCodeCitation(path=p, start_line=s, end_line=e) for p, s, e in citations],
        manual_agreement="agrees",
        differing_manual_pages=[],
        not_checked=[],
    )
    return LLMCodeAnswer(**{**fields, **overrides})


def writer(tools, result=None, error=None, **options):
    llm = FakeLLM(result=result if result is not None else structured(), error=error, provider="fake", model="fake-model")
    options.setdefault("code_date", "2026-10-30")
    return CodeAnswerWriter(llm, tools, **options), llm


def write(sut, result=None, **kwargs):
    kwargs.setdefault("manual_answer", "Zie de handleiding.")
    kwargs.setdefault("manual_pages", PAGES)
    return sut.write(result or finished(), **kwargs)


# --- a finished run becomes a structured Code Answer ------------------------------------------


def test_a_finished_run_becomes_an_answered_code_answer_with_the_search_evidence(tools):
    sut, llm = writer(tools)
    answer = write(sut)
    assert isinstance(answer, CodeAnswer)
    assert (answer.status, answer.question, answer.text) == ("answered", "Hoe werkt facturen?", "De code controleert de factuur.")
    assert answer.code_date == "2026-10-30" and answer.error is None
    assert answer.tool_calls == EVIDENCE
    assert (answer.provider, answer.model) == ("fake", "fake-model")
    assert llm.schemas == [LLMCodeAnswer]


def test_the_structuring_call_gets_the_question_manual_answer_pages_and_conclusion_only(tools):
    sut, llm = writer(tools)
    write(sut)
    (prompt,) = llm.prompts
    text = "\n".join(str(content) for _, content in prompt)
    assert prompt[0][0] == "system"
    for expected in ("Hoe werkt facturen?", "Zie de handleiding.", "Facturen.htm, Betalingen.htm", CONCLUSION):
        assert expected in text
    assert "order line" not in text  # no file contents: the model never sees code in this call


def test_without_a_manual_answer_the_prompt_says_so_and_the_verdict_is_set_by_the_code(tools):
    sut, llm = writer(tools, structured(manual_agreement="agrees", differing_manual_pages=["Facturen.htm"]))
    answer = write(sut, manual_answer=None, manual_pages=None)
    assert answer.manual_agreement == "no_manual_answer" and answer.differing_manual_pages == []
    assert "geen antwoord uit de handleiding" in str(llm.prompts[0])


# --- Code Citations: ranges validated, snippets filled by the code -------------------------------


def test_the_model_schema_has_no_snippet_so_snippets_can_never_be_invented():
    assert set(LLMCodeCitation.model_fields) == {"path", "start_line", "end_line"}


def test_a_citation_gets_its_snippet_from_the_code_checkout(tools):
    answer = write(writer(tools, structured(citations=[("src/order.p", 2, 3)]))[0])
    (citation,) = answer.citations
    assert (citation.path, citation.start_line, citation.end_line) == ("src/order.p", 2, 3)
    assert citation.snippet == "order line 2\norder line 3" and citation.snippet_truncated is False
    assert answer.dropped_citations == []


def test_a_range_longer_than_twenty_lines_keeps_its_range_but_cuts_the_snippet(tools):
    (citation,) = write(writer(tools, structured(citations=[("src/big.p", 5, 44)]))[0]).citations
    assert (citation.start_line, citation.end_line) == (5, 44) and citation.snippet_truncated is True
    assert citation.snippet.splitlines() == [f"big line {n}" for n in range(5, 25)]


def test_a_range_of_exactly_twenty_lines_is_not_truncated(tools):
    (citation,) = write(writer(tools, structured(citations=[("src/big.p", 1, 20)]))[0]).citations
    assert len(citation.snippet.splitlines()) == 20 and citation.snippet_truncated is False


@pytest.mark.parametrize("path, start, end", [
    ("src/missing.p", 1, 2),         # file does not exist
    ("src/order.p", 25, 40),         # range runs past the end of the file (30 lines)
    ("src/order.p", 31, 31),         # starts after the last line
    ("src/order.p", 0, 3),           # lines are 1-based
    ("src/order.p", 5, 3),           # reversed range
    ("data/secret.p", 1, 1),         # excluded folder: may hold customer data
    ("../outside.p", 1, 1),          # outside the Code Checkout
    ("src/order.exe", 1, 1),         # extension not on the allowlist
])
def test_citations_to_ranges_that_do_not_exist_in_the_checkout_are_dropped_and_recorded(tools, path, start, end):
    answer = write(writer(tools, structured(citations=[("src/order.p", 1, 1), (path, start, end)]))[0])
    assert [(c.path, c.start_line) for c in answer.citations] == [("src/order.p", 1)]
    assert answer.dropped_citations == [f"{path}:{start}-{end}"]
    assert answer.status == "answered"


def test_paths_are_normalised_and_duplicates_collapse_in_order(tools):
    citations = [("./src/order.p", 2, 3), ("src\\order.p", 2, 3), ("src/big.p", 1, 1), ("src/order.p", 2, 3)]
    answer = write(writer(tools, structured(citations=citations))[0])
    assert [(c.path, c.start_line, c.end_line) for c in answer.citations] == [("src/order.p", 2, 3), ("src/big.p", 1, 1)]
    assert answer.dropped_citations == []


def test_an_answer_whose_citations_all_dropped_is_flagged_uncited(tools):
    answer = write(writer(tools, structured(citations=[("src/missing.p", 1, 2)]))[0])
    assert answer.status == "answered" and answer.citations == [] and answer.uncited is True
    assert write(writer(tools)[0]).uncited is False


# --- the Manual verdict, and what was not checked ----------------------------------------------


def test_a_differing_manual_page_must_be_one_the_search_was_given(tools):
    sut, _ = writer(tools, structured(manual_agreement="differs", differing_manual_pages=["Betalingen.htm", "Verzonnen.htm"]))
    answer = write(sut)
    assert answer.manual_agreement == "differs" and answer.differing_manual_pages == ["Betalingen.htm"]


def test_agreeing_or_unknown_verdicts_carry_no_differing_pages(tools):
    for verdict in ("agrees", "unknown"):
        sut, _ = writer(tools, structured(manual_agreement=verdict, differing_manual_pages=["Facturen.htm"]))
        assert write(sut).differing_manual_pages == []


def test_what_was_not_checked_always_names_configuration_customisations_and_data(tools):
    assert ALWAYS_NOT_CHECKED == ("configuratie", "maatwerk", "data")
    sut, _ = writer(tools, structured(not_checked=["De werking van de batch-job", "Data"]))
    answer = write(sut)
    assert answer.not_checked == ["configuratie", "maatwerk", "data", "De werking van de batch-job"]  # no duplicate "Data"


# --- a stopped run stays a partial result -----------------------------------------------------


@pytest.mark.parametrize("status", ["tool_call_limit", "token_limit", "timeout", "cancelled", "error"])
def test_a_stopped_run_is_a_partial_answer_with_a_fixed_notice_and_no_llm_call(tools, status):
    sut, llm = writer(tools)
    stopped = CodeSearchResult("Hoe werkt facturen?", status, None, tool_calls=list(EVIDENCE), error="boom" if status == "error" else None)
    answer = write(sut, stopped)
    assert llm.prompts == []  # nothing is sent, nothing is concluded
    assert answer.status == status and answer.text and answer.citations == [] and answer.uncited is False
    assert answer.manual_agreement == "unknown" and answer.differing_manual_pages == []
    assert answer.tool_calls == EVIDENCE and answer.error == ("boom" if status == "error" else None)
    assert answer.code_date == "2026-10-30" and answer.not_checked[:3] == list(ALWAYS_NOT_CHECKED)


def test_stopped_notices_differ_per_status_and_say_there_is_no_conclusion(tools):
    sut, _ = writer(tools)
    texts = {s: write(sut, CodeSearchResult("v", s, None)).text for s in ("tool_call_limit", "token_limit", "timeout", "cancelled", "error")}
    assert len(set(texts.values())) == 5
    assert all("geen conclusie" in text for text in texts.values())


def test_a_stopped_run_never_uses_a_conclusion_even_if_one_is_present(tools):
    stopped = CodeSearchResult("v", "timeout", "een halve conclusie", tool_calls=[])
    assert "halve conclusie" not in write(writer(tools)[0], stopped).text


def test_a_finished_run_without_a_conclusion_is_a_partial_error(tools):
    sut, llm = writer(tools)
    answer = write(sut, finished(conclusion="  "))
    assert llm.prompts == [] and answer.status == "error" and "geen conclusie" in answer.text and answer.error


# --- when the structuring step fails, the conclusion is shown as it is ---------------------------


@pytest.mark.parametrize("error", [LLMError("the model refused"), RuntimeError("API down")])
def test_a_failed_structuring_call_falls_back_to_the_unstructured_conclusion(tools, error):
    sut, _ = writer(tools, error=error)
    answer = write(sut)
    assert answer.status == "unstructured" and answer.text == CONCLUSION
    assert answer.citations == [] and answer.manual_agreement == "unknown"
    assert answer.error == f"{type(error).__name__}: {error}" and answer.tool_calls == EVIDENCE
    assert answer.not_checked == list(ALWAYS_NOT_CHECKED)


# --- configuration gate, log ------------------------------------------------------------------


def test_the_writer_refuses_openai_unless_allowed(tools):
    llm = FakeLLM(result=structured(), provider="openai")
    with pytest.raises(CodeSearchError, match="OpenAI"):
        CodeAnswerWriter(llm, tools, code_date=None)
    CodeAnswerWriter(llm, tools, code_date=None, allow_code_to_openai=True)


def test_the_code_date_may_be_unknown(tools):
    assert write(writer(tools, code_date=None)[0]).code_date is None


def test_every_answer_is_logged_as_json(tools, tmp_path):
    log_path = tmp_path / "log" / "ask_log.jsonl"
    sut, _ = writer(tools, log=AskLog(log_path))
    write(sut)
    write(sut, CodeSearchResult("v", "timeout", None))
    first, second = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert first["kind"] == "code_answer" and first["status"] == "answered" and first["citations"][0]["path"] == "src/order.p"
    assert second["status"] == "timeout"


# --- showing it ----------------------------------------------------------------------------------


def test_format_labels_the_answer_unverified_with_code_date_citations_and_gaps(tools):
    sut, _ = writer(tools, structured(manual_agreement="differs", differing_manual_pages=["Facturen.htm"],
                                      citations=[("src/order.p", 2, 3), ("src/missing.p", 1, 1)]))
    text = format_code_answer(write(sut))
    assert "ongecontroleerd" in text.lower()
    assert "code per 2026-10-30" in text
    assert "De code controleert de factuur." in text
    assert "src/order.p:2-3" in text and "order line 2" in text
    assert "Facturen.htm" in text and "wijkt af" in text
    assert "Niet gecontroleerd: configuratie, maatwerk, data" in text
    assert "1 verwijzing" in text  # one dropped citation is mentioned, not silently lost


def test_format_of_a_partial_answer_lists_the_evidence_and_says_unstructured_citations_are_unchecked(tools):
    stopped = format_code_answer(write(writer(tools)[0], CodeSearchResult("v", "timeout", None, tool_calls=list(EVIDENCE))))
    assert "ongecontroleerd" in stopped.lower() and "grep" in stopped and "src/order.p" in stopped
    unstructured = format_code_answer(write(writer(tools, error=LLMError("x"))[0]))
    assert CONCLUSION in unstructured and "bronverwijzingen" in unstructured
    assert "bronverwijzingen" not in format_code_answer(write(writer(tools)[0]))
