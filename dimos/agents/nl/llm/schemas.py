"""Pydantic schemas for LLM structured output parsing.

Defines the data models used for LLM-based intent recognition.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Any


def _coerce_null_str(value: Any) -> str:
    return "" if value is None else str(value)


class IntentCandidate(BaseModel):
    """A candidate intent extracted from natural language.
    
    This is the primary output format for LLM-based parsing.
    The LLM extracts both the intent type and relevant slots.
    """
    
    intent_type: str = Field(
        description="The type of intent (e.g., 'move_relative', 'pick_sku', 'guard_loop')"
    )
    
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score for this intent classification"
    )
    
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted slot values for this intent"
    )
    
    reasoning: str = Field(
        default="",
        description="Brief explanation of why this intent was chosen"
    )

    @field_validator("reasoning", mode="before")
    @classmethod
    def _coerce_reasoning(cls, value: Any) -> str:
        return _coerce_null_str(value)


class MoveRelativeSlots(BaseModel):
    """Slots for relative movement intent."""
    
    direction: Literal["forward", "backward", "left", "right"] = Field(
        description="Movement direction in body frame"
    )
    
    distance_meters: float = Field(
        default=1.0,
        gt=0,
        description="Distance in meters"
    )
    
    speed: Literal["slow", "normal", "fast"] = Field(
        default="normal",
        description="Movement speed"
    )


class MoveToWorkspaceSlots(BaseModel):
    """Slots for move-to-workspace intent."""
    
    workspace_name: str = Field(
        description="Name of the target workspace"
    )
    
    workspace_color: str = Field(
        default="",
        description="Color of the workspace (if applicable)"
    )

    @field_validator("workspace_color", mode="before")
    @classmethod
    def _coerce_workspace_color(cls, value: Any) -> str:
        return _coerce_null_str(value)

    approach_direction: Literal["front", "back", "left", "right", "auto"] = Field(
        default="auto",
        description="Approach direction"
    )


class PickSkuSlots(BaseModel):
    """Slots for pick-sku intent."""
    
    workspace_type: str = Field(
        default="table",
        description="Type of workspace containing the SKU"
    )
    
    table_color: str = Field(
        description="Color of the table/workspace"
    )
    
    object_type: str = Field(
        default="cube",
        description="Type of object to pick"
    )
    
    object_color: str = Field(
        description="Color of the object to pick"
    )
    
    goal_workspace_type: str = Field(
        default="table",
        description="Type of destination workspace"
    )
    
    goal_table_color: str = Field(
        default="",
        description="Color of destination workspace (empty for default)"
    )

    @field_validator("goal_table_color", "table_color", "object_color", mode="before")
    @classmethod
    def _coerce_optional_colors(cls, value: Any) -> str:
        return _coerce_null_str(value)


class FetchSkuSlots(BaseModel):
    """Slots for fetch-sku intent."""
    
    source_workspace_name: str = Field(
        default="table",
        description="Source workspace type"
    )
    
    source_workspace_color: str = Field(
        description="Color of source workspace"
    )
    
    target_workspace_name: str = Field(
        default="table",
        description="Target workspace type"
    )
    
    target_workspace_color: str = Field(
        description="Color of target workspace"
    )
    
    sku_name: str = Field(
        default="cube",
        description="SKU type to fetch"
    )
    
    sku_color: str = Field(
        description="Color of SKU to fetch"
    )


class GuardLoopSlots(BaseModel):
    """Slots for guard/patrol loop intent."""
    
    waypoints: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of waypoints to patrol (each with workspace_name and workspace_color)"
    )
    
    loop_count: int = Field(
        default=1,
        ge=1,
        description="Number of patrol loops"
    )
    
    patrol_speed: Literal["slow", "normal", "fast"] = Field(
        default="normal",
        description="Patrol movement speed"
    )


class NLUnderstandingResult(BaseModel):
    """Complete result from LLM-based NL understanding.
    
    This is the top-level output from the LLM parsing.
    """
    
    primary_intent: IntentCandidate = Field(
        description="The primary (most likely) intent"
    )
    
    alternative_intents: list[IntentCandidate] = Field(
        default_factory=list,
        description="Alternative intents if the primary is uncertain"
    )
    
    needs_clarification: bool = Field(
        default=False,
        description="Whether user clarification is needed"
    )
    
    clarification_question: str = Field(
        default="",
        description="Question to ask user if clarification needed"
    )
    
    raw_entities: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw entities extracted from text (colors, numbers, locations)"
    )

    @field_validator("clarification_question", mode="before")
    @classmethod
    def _coerce_clarification_question(cls, value: Any) -> str:
        return _coerce_null_str(value)


class IntentValidationResult(BaseModel):
    """Result of validating LLM output against rule-based evidence.
    
    The rule layer uses this to accept, reject, or modify LLM output.
    """
    
    is_valid: bool = Field(
        description="Whether LLM result passes validation"
    )
    
    validated_slots: dict[str, Any] = Field(
        default_factory=dict,
        description="Slots after validation (may be corrected)"
    )
    
    validation_errors: list[str] = Field(
        default_factory=list,
        description="List of validation failures"
    )
    
    confidence_adjustment: float = Field(
        default=0.0,
        description="Adjustment to confidence (+/- based on validation)"
    )

    rejected_error_code: str | None = Field(
        default=None,
        description="Structured error when validation rejects LLM output",
    )


# Mapping from intent_type to slot schema
INTENT_SLOT_SCHEMAS: dict[str, type[BaseModel]] = {
    "move_relative": MoveRelativeSlots,
    "move_to_workspace": MoveToWorkspaceSlots,
    "pick_sku": PickSkuSlots,
    "fetch_sku": FetchSkuSlots,
    "guard_loop": GuardLoopSlots,
}


def get_slot_schema(intent_type: str) -> type[BaseModel] | None:
    """Get the Pydantic slot schema for an intent type."""
    return INTENT_SLOT_SCHEMAS.get(intent_type)
