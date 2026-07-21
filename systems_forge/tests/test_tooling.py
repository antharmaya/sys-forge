import pytest

from systems_forge.tooling import best_tool, require_tool


class TestBestTool:
    def test_picks_first_available_candidate(self):
        # python3 (or python) is virtually guaranteed to exist in any env
        # running this test suite at all
        result = best_tool("definitely_not_a_real_binary_xyz", "python3")
        assert result == "python3"

    def test_prefers_earlier_candidate_when_both_available(self):
        # sh and python3 are both near-universally available; sh listed
        # first must win, proving ordering (not just "any match") matters
        result = best_tool("sh", "python3")
        assert result == "sh"

    def test_returns_none_when_nothing_available(self):
        result = best_tool("definitely_not_a_real_binary_abc", "also_not_real_xyz")
        assert result is None

    def test_empty_candidates_returns_none(self):
        assert best_tool() is None


class TestRequireTool:
    def test_returns_the_found_tool(self):
        assert require_tool("definitely_not_a_real_binary_xyz", "python3") == "python3"

    def test_raises_with_a_clear_message_when_nothing_found(self):
        with pytest.raises(RuntimeError, match="not_a_real_binary_1.*not_a_real_binary_2"):
            require_tool("not_a_real_binary_1", "not_a_real_binary_2")
