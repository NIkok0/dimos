"""Tests for core protocols."""

import pytest
from dimos.agents.nl.core.protocols import ParseResult, RoutingDecision


class TestParseResult:
    """Test ParseResult dataclass."""
    
    def test_successful_parse_requires_intent_type(self):
        """Successful parse must have intent_type."""
        with pytest.raises(ValueError):
            ParseResult(success=True, intent_type=None, confidence=0.9)
    
    def test_successful_parse_requires_positive_confidence(self):
        """Successful parse must have positive confidence."""
        with pytest.raises(ValueError):
            ParseResult(success=True, intent_type="test", confidence=0.0)
        
        with pytest.raises(ValueError):
            ParseResult(success=True, intent_type="test", confidence=-0.1)
    
    def test_failed_parse_does_not_require_intent_type(self):
        """Failed parse doesn't need intent_type."""
        result = ParseResult(success=False, error_code="NO_MATCH")
        assert result.success is False
        assert result.error_code == "NO_MATCH"
    
    def test_parse_result_defaults(self):
        """Test default values."""
        result = ParseResult(success=True, intent_type="test", confidence=0.8)
        assert result.slots == {}
        assert result.error_code is None


class TestRoutingDecision:
    """Test RoutingDecision dataclass."""
    
    def test_routing_decision_creation(self):
        """Test creating a routing decision."""
        decision = RoutingDecision(
            parser_name="test_parser",
            intent_type="move_relative",
            slots={"direction": "backward", "distance_units": 20.0},
            confidence=0.95,
            alternatives=[("other_parser", 0.70)],
        )
        
        assert decision.parser_name == "test_parser"
        assert decision.intent_type == "move_relative"
        assert decision.slots["direction"] == "backward"
        assert decision.confidence == 0.95
    
    def test_routing_decision_defaults(self):
        """Test default values."""
        decision = RoutingDecision(
            parser_name="test",
            intent_type="move",
            slots={},
            confidence=0.8,
        )
        assert decision.alternatives == []
