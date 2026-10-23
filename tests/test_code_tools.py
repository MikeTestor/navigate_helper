import pytest

from navigate_helper.code_tools import MAX_READ_LINES, CodeTools, CodeToolError


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "code"
    (root / "src").mkdir(parents=True)
    (root / "src" / "order.p").write_text("DEF VAR x.\nRUN Invoice.\nMESSAGE Hello.\n", encoding="utf-8")
    (root / "src" / "notes.md").write_text("invoice notes\n", encoding="utf-8")
    (root / "src" / "logo.png").write_bytes(b"invoice")
    (root / "top.cs").write_text("class Invoice {}\n", encoding="utf-8")
    for folder in ("data", "projects", ".builder", ".claude", ".vs", "bin", "obj"):
        (root / folder).mkdir()
        (root / folder / "secret.p").write_text("invoice secret\n", encoding="utf-8")
    (root / "src" / "bin").mkdir()
    (root / "src" / "bin" / "nested.p").write_text("invoice nested\n", encoding="utf-8")
    (tmp_path / "outside.p").write_text("invoice outside\n", encoding="utf-8")
    return root


@pytest.fixture
def tools(tree):
    return CodeTools(tree)


def test_list_shows_allowed_files_and_folders_but_not_excluded_or_other_extensions(tools):
    assert tools.list(".") == ["src/", "top.cs"]
    assert tools.list("src") == ["src/notes.md", "src/order.p"]


def test_list_refuses_excluded_folders(tools):
    for folder in ("data", "projects", ".builder", ".claude", ".vs", "bin", "obj", "src/bin"):
        with pytest.raises(CodeToolError):
            tools.list(folder)


def test_read_returns_requested_range(tools):
    result = tools.read("src/order.p", start=2, limit=1)
    assert (result.path, result.start, result.end, result.total_lines) == ("src/order.p", 2, 2, 3)
    assert result.text == "RUN Invoice."
    assert result.truncated is True


def test_read_whole_small_file_is_not_truncated(tools):
    result = tools.read("src/order.p")
    assert result.text.splitlines()[0] == "DEF VAR x."
    assert (result.start, result.end, result.truncated) == (1, 3, False)


def test_read_is_capped_per_call(tree):
    (tree / "big.p").write_text("\n".join(f"line {n}" for n in range(1, 1001)), encoding="utf-8")
    result = CodeTools(tree).read("big.p", limit=100000)
    assert result.end - result.start + 1 == MAX_READ_LINES
    assert result.truncated is True
    assert result.text.splitlines()[-1] == f"line {MAX_READ_LINES}"
    follow_up = CodeTools(tree).read("big.p", start=result.end + 1)
    assert follow_up.text.splitlines()[0] == f"line {MAX_READ_LINES + 1}"


def test_read_past_the_end_is_empty(tools):
    result = tools.read("src/order.p", start=99)
    assert result.text == "" and result.truncated is False


@pytest.mark.parametrize("path", ["../outside.p", "src/../../outside.p", "src/../data/secret.p"])
def test_escape_and_excluded_paths_are_refused(tools, path):
    with pytest.raises(CodeToolError):
        tools.read(path)


def test_absolute_path_outside_is_refused(tools, tmp_path):
    with pytest.raises(CodeToolError):
        tools.read(str(tmp_path / "outside.p"))
    with pytest.raises(CodeToolError):
        tools.list(str(tmp_path))


def test_absolute_path_inside_is_accepted(tools, tree):
    assert tools.read(str(tree / "top.cs")).text == "class Invoice {}"


def test_symlink_out_of_the_root_is_refused(tree, tmp_path):
    link = tree / "src" / "link.p"
    try:
        link.symlink_to(tmp_path / "outside.p")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(CodeToolError):
        CodeTools(tree).read("src/link.p")
    assert all("outside" not in m.text for m in CodeTools(tree).grep("invoice"))


def test_disallowed_extension_and_missing_file_are_refused(tools):
    with pytest.raises(CodeToolError):
        tools.read("src/logo.png")
    with pytest.raises(CodeToolError):
        tools.read("src/missing.p")
    with pytest.raises(CodeToolError):
        tools.read("src")


def test_grep_finds_matches_only_in_allowed_files(tools):
    matches = tools.grep("invoice")
    assert [(m.path, m.line, m.text) for m in matches] == [
        ("top.cs", 1, "class Invoice {}"),
        ("src/notes.md", 1, "invoice notes"),
        ("src/order.p", 2, "RUN Invoice."),
    ]


def test_grep_can_be_case_sensitive_and_scoped_to_a_path(tools):
    assert [m.path for m in tools.grep("Invoice", ignore_case=False)] == ["top.cs", "src/order.p"]
    assert [m.path for m in tools.grep("invoice", path="src")] == ["src/notes.md", "src/order.p"]
    assert [m.path for m in tools.grep("invoice", path="top.cs")] == ["top.cs"]


def test_grep_refuses_excluded_scope_and_bad_pattern(tools):
    with pytest.raises(CodeToolError):
        tools.grep("invoice", path="data")
    with pytest.raises(CodeToolError):
        tools.grep("(")


def test_grep_is_capped(tree):
    (tree / "many.p").write_text("hit\n" * 500, encoding="utf-8")
    assert len(CodeTools(tree).grep("hit", max_matches=20)) == 20


def test_missing_root_is_an_error(tmp_path):
    with pytest.raises(CodeToolError):
        CodeTools(tmp_path / "nope")
