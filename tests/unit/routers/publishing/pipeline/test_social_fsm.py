"""Tests for SocialPipelineFSM definition.

Verifies:
- FSM has exactly 28 states (FSM_SPEC.md section 2.2, incl. cross-post F6.4)
- All expected state names exist
- State group name matches convention (*FSM suffix)
"""

from __future__ import annotations

from aiogram.fsm.state import State

from routers.publishing.pipeline._common import SocialPipelineFSM

# Expected state names from FSM_SPEC.md section 2.2
_EXPECTED_STATES = [
    # Step 1: Project selection
    "select_project",
    "create_project_name",
    "create_project_company",
    "create_project_spec",
    "create_project_url",
    # Step 2: Connection selection (TG/VK/Pinterest)
    "select_connection",
    "connect_tg_channel",
    "connect_tg_token",
    "connect_tg_verify",
    "connect_vk_group_url",
    "connect_vk_oauth",
    "connect_pinterest_oauth",
    # Step 3: Category selection
    "select_category",
    "create_category_name",
    # Step 4: Readiness check (simplified)
    "readiness_check",
    "readiness_keywords_products",
    "readiness_keywords_geo",
    "readiness_keywords_qty",
    "readiness_keywords_generating",
    "readiness_description",
    # Steps 5-7: Confirm, generate, review, publish
    "confirm_cost",
    "generating",
    "review",
    "publishing",
    "regenerating",
    # Step 8: Cross-posting (F6.4)
    "cross_post_select",
    "cross_post_running",
    "cross_post_result",
]


class TestSocialPipelineFSMDefinition:
    def test_state_count(self) -> None:
        states = [attr for attr in dir(SocialPipelineFSM) if isinstance(getattr(SocialPipelineFSM, attr), State)]
        assert len(states) == 28  # 25 base + 3 cross-post (F6.4)

    def test_all_expected_states_exist(self) -> None:
        for name in _EXPECTED_STATES:
            attr = getattr(SocialPipelineFSM, name, None)
            assert isinstance(attr, State), f"Missing state: {name}"

    def test_no_extra_states(self) -> None:
        actual = {attr for attr in dir(SocialPipelineFSM) if isinstance(getattr(SocialPipelineFSM, attr), State)}
        expected = set(_EXPECTED_STATES)
        extra = actual - expected
        assert not extra, f"Unexpected states: {extra}"

    def test_fsm_suffix(self) -> None:
        assert SocialPipelineFSM.__name__.endswith("FSM")
