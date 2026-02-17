"""Tests for ArticlePipelineFSM definition.

Verifies:
- FSM has exactly 25 states (FSM_SPEC.md section 1)
- All expected state names exist
- State group name matches convention (*FSM suffix)
"""

from __future__ import annotations

from aiogram.fsm.state import State

from routers.publishing.pipeline.article import ArticlePipelineFSM

# Expected state names from FSM_SPEC.md section 1
_EXPECTED_STATES = [
    # Step 1: Project selection
    "select_project",
    "create_project_name",
    "create_project_company",
    "create_project_spec",
    "create_project_url",
    # Step 2: WP connection check
    "select_wp",
    "connect_wp_url",
    "connect_wp_login",
    "connect_wp_password",
    # Step 3: Category selection
    "select_category",
    "create_category_name",
    # Step 4: Readiness check + inline sub-flows
    "readiness_check",
    "readiness_keywords_products",
    "readiness_keywords_geo",
    "readiness_keywords_qty",
    "readiness_keywords_generating",
    "readiness_description",
    "readiness_prices",
    "readiness_photos",
    # Step 5-8: Confirmation, generation, preview, result
    "confirm_cost",
    "generating",
    "preview",
    "publishing",
    "result",
    "regenerating",
]


class TestArticlePipelineFSMDefinition:
    """ArticlePipelineFSM has correct state definitions."""

    def test_has_exactly_25_states(self) -> None:
        """FSM_SPEC.md specifies exactly 25 states."""
        states = ArticlePipelineFSM.__all_states__
        assert len(states) == 25, f"Expected 25 states, got {len(states)}: {[s.state for s in states]}"

    def test_all_expected_states_exist(self) -> None:
        """Every expected state name is present in the FSM."""
        state_names = {s.state.split(":")[-1] for s in ArticlePipelineFSM.__all_states__}
        for expected in _EXPECTED_STATES:
            assert expected in state_names, f"Missing state: {expected}"

    def test_no_unexpected_states(self) -> None:
        """FSM does not have extra states beyond the expected 25."""
        state_names = {s.state.split(":")[-1] for s in ArticlePipelineFSM.__all_states__}
        expected_set = set(_EXPECTED_STATES)
        extra = state_names - expected_set
        assert not extra, f"Unexpected extra states: {extra}"

    def test_fsm_suffix_convention(self) -> None:
        """StatesGroup name ends with FSM (project convention)."""
        assert ArticlePipelineFSM.__name__.endswith("FSM")

    def test_states_are_state_type(self) -> None:
        """All states are proper State instances."""
        for s in ArticlePipelineFSM.__all_states__:
            assert isinstance(s, State), f"{s} is not a State instance"

    def test_state_group_prefix(self) -> None:
        """Each state's full name includes the group name."""
        for s in ArticlePipelineFSM.__all_states__:
            assert s.state.startswith("ArticlePipelineFSM:"), f"State {s.state} missing group prefix"

    def test_select_project_state(self) -> None:
        """Direct attribute access for select_project."""
        assert hasattr(ArticlePipelineFSM, "select_project")
        assert isinstance(ArticlePipelineFSM.select_project, State)

    def test_readiness_check_state(self) -> None:
        """Direct attribute access for readiness_check."""
        assert hasattr(ArticlePipelineFSM, "readiness_check")
        assert isinstance(ArticlePipelineFSM.readiness_check, State)

    def test_preview_state(self) -> None:
        """Direct attribute access for preview."""
        assert hasattr(ArticlePipelineFSM, "preview")
        assert isinstance(ArticlePipelineFSM.preview, State)

    def test_result_state(self) -> None:
        """Direct attribute access for result."""
        assert hasattr(ArticlePipelineFSM, "result")
        assert isinstance(ArticlePipelineFSM.result, State)
