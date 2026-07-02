"""Tests for PluginRegistry."""

import pytest
from dimos.agents.nl.core.registry import (
    PluginRegistry,
    PluginMetadata,
    intent_parser_registry,
)
from dimos.agents.nl.core.protocols import IntentParser, ParseResult


class MockParser:
    """Mock parser for testing."""
    
    def __init__(self, intent_type: str):
        self._intent_type = intent_type
    
    @property
    def intent_type(self) -> str:
        return self._intent_type
    
    def parse(self, text: str, context=None):
        return ParseResult(
            success=True,
            intent_type=self._intent_type,
            confidence=0.8,
        )
    
    def get_supported_slots(self):
        return []


class TestPluginRegistry:
    """Test PluginRegistry functionality."""
    
    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return PluginRegistry[MockParser](name="TestRegistry")
    
    def test_register_and_get(self, registry):
        """Test basic registration and retrieval."""
        parser = MockParser("move_relative")
        registry.register("parser1", parser, priority=100)
        
        retrieved = registry.get("parser1")
        assert retrieved is parser
    
    def test_register_duplicate_fails(self, registry):
        """Test duplicate registration fails."""
        parser = MockParser("test")
        registry.register("test", parser)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register("test", parser)
    
    def test_register_force_overwrite(self, registry):
        """Test force flag allows overwrite."""
        parser1 = MockParser("test1")
        parser2 = MockParser("test2")
        
        registry.register("test", parser1)
        registry.register("test", parser2, force=True)
        
        assert registry.get("test") is parser2
    
    def test_list_all_sorted_by_priority(self, registry):
        """Test plugins are sorted by priority."""
        parser1 = MockParser("high")
        parser2 = MockParser("medium")
        parser3 = MockParser("low")
        
        registry.register("low", parser3, priority=10)
        registry.register("high", parser1, priority=100)
        registry.register("medium", parser2, priority=50)
        
        entries = registry.list_all()
        names = [e.name for e in entries]
        
        assert names == ["high", "medium", "low"]
    
    def test_list_all_same_priority_stable_sort(self, registry):
        """Test stable sort for same priority."""
        parser1 = MockParser("first")
        parser2 = MockParser("second")
        
        registry.register("first", parser1, priority=50)
        registry.register("second", parser2, priority=50)
        
        entries = registry.list_all()
        names = [e.name for e in entries]
        
        # Same priority - should preserve registration order
        assert names == ["first", "second"]
    
    def test_unregister(self, registry):
        """Test unregistering plugins."""
        parser = MockParser("test")
        registry.register("test", parser)
        
        assert registry.unregister("test") is True
        assert registry.get("test") is None
        assert registry.unregister("test") is False  # Already removed
    
    def test_update_priority(self, registry):
        """Test updating priority."""
        parser1 = MockParser("first")
        parser2 = MockParser("second")
        
        registry.register("first", parser1, priority=50)
        registry.register("second", parser2, priority=100)
        
        # Update first to higher priority than second
        registry.update_priority("first", 150)
        
        entries = registry.list_all()
        names = [e.name for e in entries]
        
        assert names == ["first", "second"]
    
    def test_contains(self, registry):
        """Test __contains__ check."""
        parser = MockParser("test")
        registry.register("test", parser)
        
        assert "test" in registry
        assert "missing" not in registry
    
    def test_len(self, registry):
        """Test __len__ returns count."""
        assert len(registry) == 0
        
        registry.register("a", MockParser("a"))
        assert len(registry) == 1
        
        registry.register("b", MockParser("b"))
        assert len(registry) == 2
    
    def test_list_by_tag(self, registry):
        """Test filtering by tag."""
        registry.register("a", MockParser("a"), tags=["navigation"])
        registry.register("b", MockParser("b"), tags=["manipulation"])
        registry.register("c", MockParser("c"), tags=["navigation"])
        
        nav_entries = registry.list_by_tag("navigation")
        assert len(nav_entries) == 2
        
        names = {e.name for e in nav_entries}
        assert names == {"a", "c"}
    
    def test_list_by_intent_type(self, registry):
        """Test filtering by intent_type."""
        registry.register("a", MockParser("move_relative"))
        registry.register("b", MockParser("pick_sku"))
        registry.register("c", MockParser("move_relative"))
        
        move_entries = registry.list_by_intent_type("move_relative")
        assert len(move_entries) == 2
    
    def test_clear(self, registry):
        """Test clearing registry."""
        registry.register("a", MockParser("a"))
        registry.register("b", MockParser("b"))
        
        registry.clear()
        
        assert len(registry) == 0
        assert "a" not in registry
    
    def test_iteration(self, registry):
        """Test iterating over registry."""
        registry.register("b", MockParser("b"), priority=10)
        registry.register("a", MockParser("a"), priority=100)
        
        names = [entry.name for entry in registry]
        # Should be in priority order
        assert names == ["a", "b"]


class TestPluginMetadata:
    """Test PluginMetadata dataclass."""
    
    def test_metadata_creation(self):
        """Test creating metadata."""
        meta = PluginMetadata(
            priority=100,
            version="2.0.0",
            description="Test parser",
            author="Test Team",
            tags=["navigation", "move"],
        )
        
        assert meta.priority == 100
        assert meta.version == "2.0.0"
        assert meta.tags == ["navigation", "move"]
    
    def test_metadata_defaults(self):
        """Test default values."""
        meta = PluginMetadata()
        
        assert meta.priority == 0
        assert meta.version == "1.0.0"
        assert meta.description == ""
        assert meta.tags == []


class TestGlobalRegistry:
    """Test the global registries."""
    
    def test_global_registry_exists(self):
        """Test global registry is available."""
        assert intent_parser_registry is not None
    
    def test_global_registry_is_plugin_registry(self):
        """Test global registry is correct type."""
        assert isinstance(intent_parser_registry, PluginRegistry)
