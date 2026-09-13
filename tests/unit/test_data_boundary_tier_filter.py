"""Tests for AgenticExecutor._apply_data_boundary_to_tiers.

Incident 2026-07-21: community_host (local_only role, data_boundary
allowed_tiers=['free']) was unable to restart for 28+ days. Root cause:
_determine_tier_preference_for_iteration's dynamic complexity policy could
reorder FREE_API into a role's candidate tier list with no awareness of the
role's data_boundary restriction. ResourceManager.acquire() would then
happily acquire a free_api resource, and the task failed outright with
"Data boundary violation" AFTER acquisition instead of ever considering an
allowed tier. See ~/.memory/research/community_host_tier_boundary_fix_2607.md.
"""
import unittest

from app.scheduler.agentic_executor import AgenticExecutor
from app.scheduler.resource_pool import ResourceTier


class TestApplyDataBoundaryToTiers(unittest.TestCase):
    def test_no_allowed_tiers_config_is_a_no_op(self):
        tiers = [ResourceTier.FREE_API, ResourceTier.FREE]
        result = AgenticExecutor._apply_data_boundary_to_tiers(tiers, None)
        self.assertEqual(result, tiers)

    def test_empty_allowed_tiers_config_is_a_no_op(self):
        tiers = [ResourceTier.FREE_API, ResourceTier.FREE]
        result = AgenticExecutor._apply_data_boundary_to_tiers(tiers, [])
        self.assertEqual(result, tiers)

    def test_filters_out_disallowed_tier_preserving_order(self):
        # The exact community_host scenario: dynamic policy proposed
        # [FREE_API, FREE] but the role only allows ['free'].
        tiers = [ResourceTier.FREE_API, ResourceTier.FREE]
        result = AgenticExecutor._apply_data_boundary_to_tiers(tiers, ["free"])
        self.assertEqual(result, [ResourceTier.FREE])

    def test_allowed_tier_not_in_candidate_list_falls_back_to_role_tiers(self):
        # Dynamic policy proposed only tiers the role can't use at all.
        tiers = [ResourceTier.FREE_API, ResourceTier.PAID]
        result = AgenticExecutor._apply_data_boundary_to_tiers(tiers, ["free"])
        self.assertEqual(result, [ResourceTier.FREE])

    def test_multiple_allowed_tiers_preserves_relative_order(self):
        tiers = [ResourceTier.PAID, ResourceTier.FREE_API, ResourceTier.FREE]
        result = AgenticExecutor._apply_data_boundary_to_tiers(tiers, ["free", "free_api"])
        self.assertEqual(result, [ResourceTier.FREE_API, ResourceTier.FREE])

    def test_all_tiers_already_allowed_is_unchanged(self):
        tiers = [ResourceTier.FREE, ResourceTier.FREE_API, ResourceTier.PAID]
        result = AgenticExecutor._apply_data_boundary_to_tiers(
            tiers, ["free", "free_api", "paid"]
        )
        self.assertEqual(result, tiers)


if __name__ == "__main__":
    unittest.main()
