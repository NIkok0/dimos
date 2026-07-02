"""Tests for workspace extractor."""

from dimos.agents.nl.extractors.workspace import (
    extract_workspace,
    extract_workspace_name,
    extract_workspace_color,
)


class TestExtractWorkspaceFront:
    """Test front workspace extraction."""
    
    def test_front_workspace_full(self):
        """前方固定工作区"""
        name, color = extract_workspace("移动到前方固定工作区")
        assert name == "front_workspace"
        assert color == ""
    
    def test_front_workspace_short(self):
        """前方工作区"""
        name, color = extract_workspace("前往前方工作区")
        assert name == "front_workspace"
        assert color == ""
    
    def test_front_workspace_english(self):
        """front_workspace"""
        name, color = extract_workspace("go to front_workspace")
        assert name == "front_workspace"
        assert color == ""


class TestExtractWorkspaceTable:
    """Test table workspace extraction (requires color)."""
    
    def test_red_table(self):
        """红色桌子"""
        name, color = extract_workspace("前往红色桌子")
        assert name == "table"
        assert color == "red"
    
    def test_blue_table(self):
        """蓝色桌子"""
        name, color = extract_workspace("蓝色桌子")
        assert name == "table"
        assert color == "blue"
    
    def test_table_no_color(self):
        """桌子 without color"""
        name, color = extract_workspace("前往桌子")
        # Should not match because table requires color
        assert name is None
    
    def test_table_english(self):
        """red table in English"""
        name, color = extract_workspace("go to the red table")
        assert name == "table"
        assert color == "red"


class TestExtractWorkspaceConvenience:
    """Test convenience functions."""
    
    def test_extract_name_only(self):
        """extract_workspace_name returns only name"""
        name = extract_workspace_name("前往红色桌子")
        assert name == "table"
    
    def test_extract_color_only(self):
        """extract_workspace_color returns only color"""
        color = extract_workspace_color("前往红色桌子")
        assert color == "red"
    
    def test_extract_color_empty(self):
        """extract_workspace_color returns empty string if no color"""
        color = extract_workspace_color("前方工作区")
        assert color == ""


class TestExtractWorkspaceNoMatch:
    """Test cases that should not match."""
    
    def test_no_workspace(self):
        """Text without workspace keywords"""
        name, color = extract_workspace("向后移动")
        assert name is None
    
    def test_empty_text(self):
        """Empty text"""
        name, color = extract_workspace("")
        assert name is None
