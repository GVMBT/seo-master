"""Tests for services.keywords — data-first keyword pipeline."""

from __future__ import annotations

import pytest

from services.keywords import KeywordService


class TestFilterLowQuality:
    """Test filter_low_quality method."""

    @pytest.fixture
    def service(self) -> KeywordService:
        """Create a KeywordService with mocked deps (unused in filter)."""
        return KeywordService.__new__(KeywordService)

    def test_removes_ai_zero_volume(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "real phrase",
                "total_volume": 100,
                "avg_difficulty": 50,
                "phrases": [
                    {"phrase": "real phrase", "volume": 100, "ai_suggested": False},
                    {"phrase": "ai junk", "volume": 0, "ai_suggested": True},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert len(result) == 1
        assert len(result[0]["phrases"]) == 1
        assert result[0]["phrases"][0]["phrase"] == "real phrase"

    def test_keeps_dataseo_zero_volume(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "rare phrase",
                "total_volume": 0,
                "avg_difficulty": 0,
                "phrases": [
                    {"phrase": "rare phrase", "volume": 0, "ai_suggested": False},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert len(result) == 1
        assert len(result[0]["phrases"]) == 1

    def test_keeps_ai_with_volume(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "good ai phrase",
                "total_volume": 50,
                "avg_difficulty": 30,
                "phrases": [
                    {"phrase": "good ai phrase", "volume": 50, "ai_suggested": True},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert len(result) == 1
        assert len(result[0]["phrases"]) == 1

    def test_removes_empty_clusters(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "all junk",
                "cluster_type": "article",
                "main_phrase": "junk",
                "total_volume": 0,
                "avg_difficulty": 0,
                "phrases": [
                    {"phrase": "junk1", "volume": 0, "ai_suggested": True},
                    {"phrase": "junk2", "volume": 0, "ai_suggested": True},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert len(result) == 0

    def test_updates_main_phrase_if_removed(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "removed phrase",
                "total_volume": 100,
                "avg_difficulty": 50,
                "phrases": [
                    {"phrase": "removed phrase", "volume": 0, "ai_suggested": True},
                    {"phrase": "kept phrase", "volume": 100, "ai_suggested": False},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert result[0]["main_phrase"] == "kept phrase"

    def test_recalculates_aggregates(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "a",
                "total_volume": 150,
                "avg_difficulty": 40,
                "phrases": [
                    {"phrase": "a", "volume": 100, "difficulty": 30, "ai_suggested": False},
                    {"phrase": "b", "volume": 50, "difficulty": 50, "ai_suggested": False},
                    {"phrase": "c", "volume": 0, "difficulty": 0, "ai_suggested": True},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert result[0]["total_volume"] == 150
        assert result[0]["avg_difficulty"] == 40  # (30+50)//2

    def test_no_filtering_when_all_good(self, service: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "a",
                "total_volume": 200,
                "avg_difficulty": 50,
                "phrases": [
                    {"phrase": "a", "volume": 100, "ai_suggested": False},
                    {"phrase": "b", "volume": 100, "ai_suggested": False},
                ],
            }
        ]
        result = service.filter_low_quality(clusters)
        assert len(result) == 1
        assert len(result[0]["phrases"]) == 2
