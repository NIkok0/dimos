"""LLM-based natural language parsing.

This module provides LLM-driven intent parsing with rule-based fallback
and validation. The architecture:

1. LLM as primary parser: Uses structured output / function calling
2. Rules as fast-path: Simple patterns bypass LLM for speed
3. Rules as validation: LLM results are validated against text evidence
"""
