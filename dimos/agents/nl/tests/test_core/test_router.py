"""Tests for IntentRouter."""

import pytest
from dimos.agents.nl.core.router import (
    IntentRouter,
    RouterConfig,
    AmbiguityError,
    ContextDisambiguator,
    ThresholdDisambiguator,
)
from dimos.agents.nl.core.registry import PluginRegistry
from dimos.agents.nl.core.protocols import IntentParser, ParseResult


class MockParser:
    """Mock parser for testing."""
    
    def __init__(self, intent_type: str, confidence: float = 0.8):
        self._intent_type = intent_type
        self._confidence = confidence
    
    @property
    def intent_type(self) -> str:
        return self._intent_type
    
    def parse(self, text: str, context=None):
        # Simple matching: if intent_type is in text
        if self._intent_type in text.lower():
            return ParseResult(
                success=True,
                intent_type=self._intent_type,
                confidence=self._confidence,
            )
        return ParseResult(success=False, error_code="NO_MATCH")
    
    def get_supported_slots(self):
        return ["slot1"]


class TestIntentRouter:
    """Test IntentRouter routing logic."""
    
    @pytest.fixture
    def registry(self):
        """Create a fresh registry."""
        return PluginRegistry[IntentParser](name="TestRegistry")
    
    @pytest.fixture
    def router(self, registry):
        """Create router with default config."""
        return IntentRouter(registry, RouterConfig(min_confidence=0.5))
    
    def test_route_single_match(self, registry, router):
        """Test routing to single matching parser."""
        registry.register("move", MockParser("move", confidence=0.9), priority=100)
        
        decision = router.route("please move forward")
        
        assert decision is not None
        assert decision.intent_type == "move"
        assert decision.confidence == 0.9
        assert decision.alternatives == []
    
    def test_route_no_match(self, registry, router):
        """Test routing when no parser matches."""
        registry.register("move", MockParser("move"), priority=100)
        
        decision = router.route("completely unrelated text")
        
        assert decision is None
    
    def test_route_multiple_choices_best_wins(self, registry, router):
        """Test routing picks highest confidence match."""
        registry.register("move", MockParser("move", confidence=0.7), priority=50)
        registry.register("pick", MockParser("pick", confidence=0.9), priority=100)
        
        # Text contains both "move" and "pick"
        decision = router.route("please move and pick")
        
        assert decision.intent_type == "pick"
        assert decision.confidence == 0.9
    
    def test_route_alternatives_included(self, registry, router):
        """Test alternatives are included in decision."""
        registry.register("move", MockParser("move", confidence=0.9), priority=100)
        registry.register("pick", MockParser("pick", confidence=0.8), priority=90)
        registry.register("scan", MockParser("scan", confidence=0.7), priority=80)
        
        decision = router.route("move pick scan text")
        
        # Should have 2 alternatives (max_alternatives defaults to 2)
        assert len(decision.alternatives) == 2
        # Alternatives ordered by confidence
        assert decision.alternatives[0][1] >= decision.alternatives[1][1]
    
    def test_route_below_min_confidence_rejected(self, registry):
        """Test results below min_confidence are rejected."""
        registry.register("low", MockParser("low", confidence=0.3), priority=100)
        
        router = IntentRouter(registry, RouterConfig(min_confidence=0.5))
        
        decision = router.route("low text")
        
        assert decision is None
    
    def test_route_empty_text(self, router):
        """Test routing with empty text."""
        assert router.route("") is None
        assert router.route("   ") is None
    
    def test_route_parser_exception_handled(self, registry, router):
        """Test exceptions in parsers are handled gracefully."""
        
        class FailingParser:
            @property
            def intent_type(self):
                return "failing"
            
            def parse(self, text, context=None):
                raise ValueError("Simulated failure")
            
            def get_supported_slots(self):
                return []
        
        registry.register("good", MockParser("good"), priority=50)
        registry.register("bad", FailingParser(), priority=100)
        
        # Should not crash, should return good parser result
        decision = router.route("good text")
        
        assert decision is not None
        assert decision.intent_type == "good"
    
    def test_route_all_returns_all_matches(self, registry, router):
        """Test route_all returns all matches."""
        registry.register("a", MockParser("a", confidence=0.9), priority=100)
        registry.register("b", MockParser("b", confidence=0.7), priority=90)
        
        results = router.route_all("a b text")
        
        assert len(results) == 2
        # Sorted by confidence desc
        assert results[0][2] >= results[1][2]
    
    def test_get_parser_for_intent_type(self, registry, router):
        """Test getting parser by intent type."""
        parser = MockParser("move")
        registry.register("move", parser, priority=100)
        
        retrieved = router.get_parser_for_intent_type("move")
        
        assert retrieved is parser
    
    def test_get_parser_for_unknown_intent_type(self, registry, router):
        """Test getting parser for unknown intent type."""
        result = router.get_parser_for_intent_type("unknown")
        
        assert result is None


class TestRouterConfig:
    """Test RouterConfig."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = RouterConfig()
        
        assert config.min_confidence == 0.5
        assert config.ambiguity_threshold == 0.15
        assert config.max_alternatives == 2
        assert config.enable_fallback is False
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = RouterConfig(
            min_confidence=0.7,
            ambiguity_threshold=0.1,
            max_alternatives=3,
            enable_fallback=True,
            fallback_parser_name="default",
        )
        
        assert config.min_confidence == 0.7
        assert config.ambiguity_threshold == 0.1
        assert config.max_alternatives == 3
        assert config.enable_fallback is True


class TestDisambiguators:
    """Test disambiguator classes."""
    
    def test_context_disambiguator_chooses_first(self):
        """Test ContextDisambiguator defaults to first alternative."""
        disambiguator = ContextDisambiguator()
        
        alternatives = [
            ("parser_a", ParseResult(success=True, intent_type="a", confidence=0.8), 0.8),
            ("parser_b", ParseResult(success=True, intent_type="b", confidence=0.75), 0.75),
        ]
        
        chosen = disambiguator.choose(alternatives, "test text")
        
        assert chosen == 0
    
    def test_threshold_disambiguator_almost_tied_warning(self, tmp_path):
        """Test ThresholdDisambiguator warns on near ties."""
        from dimos.utils import logging_config
        from dimos.utils.logging_config import set_run_log_dir

        logging_config._RUN_LOG_DIR = None
        logging_config._LOG_FILE_PATH = None
        set_run_log_dir(tmp_path / "logs")
        disambiguator = ThresholdDisambiguator(force_second_threshold=0.05)
        
        alternatives = [
            ("parser_a", ParseResult(success=True, intent_type="a", confidence=0.81), 0.81),
            ("parser_b", ParseResult(success=True, intent_type="b", confidence=0.80), 0.80),
        ]
        
        chosen = disambiguator.choose(alternatives, "test")
        
        # Should log warning about near tie
        main_log = tmp_path / "logs" / "main.jsonl"
        assert "Nearly tied confidences" in main_log.read_text()
        # But still chooses first
        assert chosen == 0
