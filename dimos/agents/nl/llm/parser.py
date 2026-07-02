"""LLM-based intent parser.

Uses LLM (GPT-4, Claude, etc.) with structured output to parse natural language.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from dimos.agents.nl.core.protocols import IntentParser, ParseResult
from dimos.agents.nl.llm.schemas import (
    NLUnderstandingResult,
    IntentCandidate,
    IntentValidationResult,
)
from dimos.agents.nl.llm.prompts import build_parsing_prompt, build_system_prompt

try:
    from dimos.agents.chat_model_factory import make_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class LLMValidator(Protocol):
    """Protocol for validating LLM output against rule-based evidence."""
    
    def validate(
        self,
        candidate: IntentCandidate,
        raw_text: str,
    ) -> IntentValidationResult:
        """Validate LLM output against text evidence.
        
        Returns validation result with any corrections.
        """
        ...


class LLMIntentParser(IntentParser):
    """Parser that uses LLM with structured output for intent recognition.
    
    This parser:
    1. Sends user text to LLM with structured parsing prompt
    2. Receives structured output (intent_type + slots)
    3. Validates output against rule-based evidence (optional)
    4. Returns ParseResult
    
    Example:
        parser = LLMIntentParser(model="gpt-4o")
        result = parser.parse("向后移动1米")
        # result.intent_type == "move_relative"
        # result.slots == {"direction": "backward", "distance_meters": 1.0}
    """
    
    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.1,
        validator: LLMValidator | None = None,
        use_structured_output: bool = True,
        include_few_shot: bool = True,
        catalog: Any | None = None,
    ):
        """Initialize LLM parser.
        
        Args:
            model: Model name (gpt-4o, claude-3-opus, etc.)
            temperature: LLM temperature (lower for more deterministic parsing)
            validator: Optional validator to check LLM output against rules
            use_structured_output: Whether to use native structured output
            include_few_shot: Whether to include few-shot examples in prompt
            catalog: NL semantic catalog for dynamic prompts
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain required for LLMIntentParser")
        
        self._model_name = model
        self._temperature = temperature
        self._validator = validator
        self._use_structured_output = use_structured_output
        self._include_few_shot = include_few_shot
        self._catalog = catalog
        self._system_prompt = build_system_prompt(catalog)
        
        # Initialize LLM
        try:
            self._llm = make_chat_model(
                model,
                temperature=temperature,
            )
            logger.info(f"Initialized LLM parser with model: {model}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise
    
    @property
    def intent_type(self) -> str:
        """Returns 'llm_parsed' as this parser handles multiple intent types."""
        return "llm_parsed"
    
    def parse(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> ParseResult:
        """Parse text using LLM.
        
        Args:
            text: User instruction
            context: Optional context (conversation history, current state, etc.)
        
        Returns:
            ParseResult with LLM-extracted intent and slots
        """
        if not text or not text.strip():
            return ParseResult(
                success=False,
                error_code="EMPTY_INPUT",
            )
        
        try:
            # Build prompt
            prompt = build_parsing_prompt(
                text,
                include_examples=self._include_few_shot,
                context=context,
                catalog=self._catalog,
            )
            
            # Call LLM
            if self._use_structured_output:
                result = self._parse_with_structured_output(prompt, text, context)
            else:
                result = self._parse_with_json_mode(prompt, text, context)
            
            # Validate if validator provided
            if self._validator and result.success:
                validated = self._validator.validate(
                    IntentCandidate(
                        intent_type=result.intent_type or "",
                        confidence=result.confidence,
                        slots=result.slots,
                    ),
                    text,
                )
                
                if not validated.is_valid:
                    logger.warning(
                        f"LLM output failed validation: {validated.validation_errors}"
                    )
                    return ParseResult(
                        success=False,
                        error_code=validated.rejected_error_code or "VALIDATION_FAILED",
                    )

                # Use validated slots
                return ParseResult(
                    success=True,
                    intent_type=result.intent_type,
                    slots=validated.validated_slots,
                    confidence=result.confidence + validated.confidence_adjustment,
                )
            
            return result
            
        except Exception as e:
            logger.error(f"LLM parsing failed: {e}", exc_info=True)
            return ParseResult(
                success=False,
                error_code="LLM_ERROR",
            )
    
    def _parse_with_structured_output(
        self,
        prompt: str,
        raw_text: str,
        context: dict[str, Any] | None,
    ) -> ParseResult:
        """Parse using native structured output (OpenAI/Anthropic function calling)."""
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=prompt),
        ]
        
        # Try to use with_structured_output if available
        try:
            structured_llm = self._llm.with_structured_output(NLUnderstandingResult)
            result: NLUnderstandingResult | None = structured_llm.invoke(messages)
            if result is None:
                raise ValueError("structured output returned None")
        except (AttributeError, NotImplementedError, ValueError):
            # Fallback to regular invoke + parsing
            response = self._llm.invoke(messages)
            result = self._parse_response(str(response.content))
        
        return self._convert_to_parse_result(result, raw_text)
    
    def _parse_with_json_mode(
        self,
        prompt: str,
        raw_text: str,
        context: dict[str, Any] | None,
    ) -> ParseResult:
        """Parse using JSON mode (fallback)."""
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=prompt + "\n\nRespond with valid JSON only."),
        ]
        
        # Try to use JSON mode
        try:
            response = self._llm.invoke(
                messages,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Fallback to regular invoke
            response = self._llm.invoke(messages)
        
        result = self._parse_response(str(response.content))
        return self._convert_to_parse_result(result, raw_text)
    
    def _parse_response(self, content: str) -> NLUnderstandingResult:
        """Parse LLM response into NLUnderstandingResult."""
        # Extract JSON if wrapped in markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        # Parse JSON
        data = json.loads(content.strip())
        if data.get("clarification_question") is None:
            data["clarification_question"] = ""
        primary = data.get("primary_intent")
        if isinstance(primary, dict) and primary.get("reasoning") is None:
            primary["reasoning"] = ""
        return NLUnderstandingResult(**data)
    
    def _convert_to_parse_result(
        self,
        result: NLUnderstandingResult,
        raw_text: str,
    ) -> ParseResult:
        """Convert NLUnderstandingResult to ParseResult."""
        if result is None or not result.primary_intent:
            return ParseResult(
                success=False,
                error_code="NEED_CLARIFICATION",
            )

        primary = result.primary_intent

        if result.needs_clarification:
            return ParseResult(
                success=False,
                error_code="NEED_CLARIFICATION",
            )
        if primary.confidence < 0.5:
            return ParseResult(
                success=False,
                error_code="LOW_CONFIDENCE",
            )
        
        # Convert distance from meters to internal units if needed
        slots = dict(primary.slots)
        if "distance_meters" in slots:
            from dimos.agents.nl.extractors.distance import meters_to_relative_distance_units
            try:
                slots["distance_units"] = meters_to_relative_distance_units(
                    float(slots.pop("distance_meters"))
                )
            except (TypeError, ValueError):
                return ParseResult(
                    success=False,
                    error_code="INVALID_SLOT",
                )
        
        return ParseResult(
            success=True,
            intent_type=primary.intent_type,
            slots=slots,
            confidence=primary.confidence,
        )
    
    def get_supported_slots(self) -> list[str]:
        """Returns all possible slot names across all intent types."""
        return [
            "direction", "distance_meters", "distance_units", "speed",
            "workspace_name", "workspace_color", "approach_direction",
            "workspace_type", "table_color", "object_type", "object_color",
            "goal_workspace_type", "goal_table_color",
            "source_workspace_name", "source_workspace_color",
            "target_workspace_name", "target_workspace_color",
            "sku_name", "sku_color",
            "waypoints", "loop_count", "patrol_speed",
        ]


# Convenience factory functions

def make_gpt4o_parser(**kwargs) -> LLMIntentParser:
    """Create parser using GPT-4o."""
    return LLMIntentParser(model="gpt-4o", **kwargs)


def make_claude_parser(**kwargs) -> LLMIntentParser:
    """Create parser using Claude 3."""
    return LLMIntentParser(model="claude-3-opus-20240229", **kwargs)
