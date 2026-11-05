import json
import warnings

import pytest

from navigate_helper.ask_log import AskLog


def test_write_appends_one_json_line_with_timestamp_before_the_record(tmp_path):
    log = AskLog(tmp_path / "sub" / "ask_log.jsonl")
    log.write({"question": "één", "covered": True, "provider": "fake", "model": "m"})
    log.write({"question": "twee", "covered": False, "provider": "fake", "model": "m"})
    lines = (tmp_path / "sub" / "ask_log.jsonl").read_text(encoding="utf-8").splitlines()
    first, second = [json.loads(line) for line in lines]
    assert list(first) == ["timestamp", "question", "covered", "provider", "model"]
    assert first["provider"] == "fake" and first["model"] == "m" and first["timestamp"] and first["question"] == "één"
    assert second["question"] == "twee" and second["covered"] is False


def test_non_ascii_is_written_as_is(tmp_path):
    AskLog(tmp_path / "log.jsonl").write({"question": "één"})
    assert "één" in (tmp_path / "log.jsonl").read_text(encoding="utf-8")


def test_a_write_failure_only_warns(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.warns(UserWarning, match="ask log"):
        AskLog(blocker / "ask_log.jsonl").write({"question": "vraag"})


def test_no_warning_when_writing_works(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        AskLog(tmp_path / "log.jsonl").write({"question": "vraag"})
