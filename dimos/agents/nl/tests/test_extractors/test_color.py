"""Tests for color extractor."""

from dimos.agents.nl.extractors.color import (
    extract_colors_in_order,
    extract_first_color,
    is_color_mentioned,
    COLOR_ALIASES,
)


class TestExtractColorsInOrder:
    """Test extracting colors in order of appearance."""
    
    def test_single_color(self):
        """Extract single color"""
        colors = extract_colors_in_order("红色的方块")
        assert colors == ["red"]
    
    def test_multiple_colors(self):
        """Extract multiple colors in order"""
        colors = extract_colors_in_order("把红色方块放到蓝色桌子上")
        assert colors == ["red", "blue"]
    
    def test_english_colors(self):
        """Extract English colors"""
        colors = extract_colors_in_order("pick up the green cube")
        assert colors == ["green"]
    
    def test_no_colors(self):
        """No colors in text"""
        colors = extract_colors_in_order("move forward")
        assert colors == []


class TestExtractFirstColor:
    """Test extracting first color."""
    
    def test_first_color(self):
        """Get first color only"""
        color = extract_first_color("红色和蓝色")
        assert color == "red"
    
    def test_exclude_color(self):
        """Exclude specific color"""
        color = extract_first_color("绿色和红色", exclude={"green"})
        assert color == "red"
    
    def test_no_color(self):
        """No color found"""
        color = extract_first_color("move forward")
        assert color is None


class TestIsColorMentioned:
    """Test checking if color is mentioned."""
    
    def test_specific_color_mentioned(self):
        """Check specific color"""
        assert is_color_mentioned("红色方块", "red") is True
        assert is_color_mentioned("红色方块", "blue") is False
    
    def test_any_color_mentioned(self):
        """Check any color"""
        assert is_color_mentioned("绿色的物体") is True
        assert is_color_mentioned("move forward") is False


class TestColorAliases:
    """Test color alias definitions."""
    
    def test_all_colors_have_aliases(self):
        """All colors have at least one alias"""
        for color, aliases in COLOR_ALIASES.items():
            assert len(aliases) > 0
            # First alias should be the English canonical name
            assert aliases[0] == color
