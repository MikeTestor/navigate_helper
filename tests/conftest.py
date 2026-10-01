from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pages_dir() -> Path:
    """The four small committed fixture Manual Pages."""
    return FIXTURES / "pages"
