"""Prompt templates for LLM-based NL parsing.

Defines system prompts and few-shot examples for structured output parsing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dimos.agents.nl.navigation_semantic_catalog import NlSemanticCatalog

NL_PARSER_SYSTEM_PROMPT = """You are a natural language parser for a mobile manipulation robot.

Your task is to analyze user instructions and extract structured intent information.

## Parsing Guidelines

1. Extract all relevant slots from the instruction
2. Use defaults when information is missing:
   - distance: 1.0 meter (if direction given but no distance)
   - speed: "normal"
   - object_type: "cube"
   - workspace_type: "table"
   - loop_count: 1

3. Support both Chinese and English
4. If the instruction is ambiguous, mark needs_clarification=True
5. Provide reasoning for your intent classification

## Intent Disambiguation (CRITICAL)

- **pick_sku**: pick up an object from ONE workspace. Triggers: 抓/拿/取/抓取/拿取/pick/grab.
  ONLY one source workspace + object. NO target/destination workspace mentioned.
  Example: "去蓝色桌子抓红色方块" → pick_sku.
- **fetch_sku**: move an object FROM a source workspace TO a different target workspace.
  Triggers: 送到/拿到...放到/从...拿到/搬/fetch/relocate/deliver.
  Requires BOTH source and target (typically 3 colors: source, sku, target).
  Example: "把红色方块从蓝色桌子送到绿色桌子" → fetch_sku (3 colors).
  If only ONE workspace + object is mentioned, it is pick_sku, NOT fetch_sku.
- **move_relative**: relative direction move (forward/backward/left/right) + distance.
  Triggers: 向前/向后/向左/向右/前进/后退/move/go + direction.
  Must NOT contain pick/fetch/grab object words.
- **move_to_workspace**: navigate to a named workspace (front_workspace / colored table).
  Triggers: 去/前往/移动到/navigate to + workspace alias, WITHOUT object pickup.
- **guard_loop**: patrol between 2+ waypoints. Triggers: 巡逻/守卫/patrol/guard + loop count.

When the instruction does NOT clearly match any intent above (e.g. unrelated task,
impossible action, missing required slots after defaults applied), you MUST return
needs_clarification=True or a primary_intent with confidence < 0.5. Do NOT force-fit
an ambiguous instruction into pick_sku or fetch_sku.

## Clarification Policy

- Set needs_clarification=True only when required slots for the chosen intent cannot be determined.
- For pick_sku: goal workspace is optional and defaults to the source table. Do NOT ask for clarification when only post-pick placement is unspecified.
- For fetch_sku: both source and target workspaces must be present or needs_clarification=True.
- For unsupported/impossible requests (e.g. "fly to the moon", "cook dinner"): return
  needs_clarification=True with confidence < 0.5. Do NOT map them to any supported intent.

## Distance Parsing

Convert natural language distances to meters:
- "1米" / "1m" / "one meter" -> 1.0
- "两格" / "2 cells" -> 0.1 (assuming 0.05m per cell)
- "一点" / "a bit" / "slightly" -> 0.5
- "一步" / "one step" -> 0.5

## Response Format

Respond with a JSON object matching the NLUnderstandingResult schema:
- primary_intent: The most likely intent with confidence
- alternative_intents: Other possible intents (if uncertain)
- needs_clarification: True if user input is unclear
- clarification_question: Question to ask if clarification needed
"""


def build_system_prompt(catalog: NlSemanticCatalog | None = None) -> str:
    """Build system prompt with intent types and color mapping from catalog."""
    parts = [NL_PARSER_SYSTEM_PROMPT.strip(), "\n## Available Intent Types\n"]
    if catalog is None:
        parts.append(_fallback_intent_section())
    else:
        for intent_type, spec in catalog.intents.items():
            slots = ", ".join(spec.llm_slots) if spec.llm_slots else "see schema"
            desc = spec.description or intent_type
            parts.append(f"- **{intent_type}**: {desc}")
            parts.append(f"  - Slots: {slots}")
        parts.append("\n## Color Mapping\n")
        for color, spec in catalog.colors.items():
            aliases = ", ".join(spec.aliases)
            parts.append(f"- {color}: {aliases}")
        parts.append("\n## Workspaces\n")
        for ws_name, spec in catalog.workspaces.items():
            aliases = ", ".join(spec.aliases[:5])
            color_req = "requires color" if spec.requires_color else "no color required"
            parts.append(f"- {ws_name} ({color_req}): {aliases}")
    return "\n".join(parts)


def _fallback_intent_section() -> str:
    return """
1. **move_relative**: direction, distance_meters, speed
2. **move_to_workspace**: workspace_name, workspace_color
3. **pick_sku**: workspace_type, table_color, object_type, object_color
4. **fetch_sku**: source/target workspace colors, sku_name, sku_color
5. **guard_loop**: waypoints, loop_count
""".strip()


# Few-shot examples for better parsing accuracy

FEW_SHOT_EXAMPLES = [
    {
        "input": "向后移动1米",
        "output": {
            "primary_intent": {
                "intent_type": "move_relative",
                "confidence": 0.95,
                "slots": {
                    "direction": "backward",
                    "distance_meters": 1.0,
                    "speed": "normal"
                },
                "reasoning": "Explicit direction '向后' (backward) and distance '1米' (1 meter)"
            },
            "alternative_intents": [],
            "needs_clarification": False,
            "raw_entities": [
                {"type": "direction", "value": "backward", "text": "向后"},
                {"type": "distance", "value": 1.0, "text": "1米"}
            ]
        }
    },
    {
        "input": "抓取红色方块放到蓝色桌子上",
        "output": {
            "primary_intent": {
                "intent_type": "pick_sku",
                "confidence": 0.92,
                "slots": {
                    "workspace_type": "table",
                    "table_color": "red",
                    "object_type": "cube",
                    "object_color": "red",
                    "goal_workspace_type": "table",
                    "goal_table_color": "blue"
                },
                "reasoning": "Object '红色方块' (red cube) on source, destination '蓝色桌子' (blue table)"
            },
            "alternative_intents": [
                {
                    "intent_type": "fetch_sku",
                    "confidence": 0.3,
                    "slots": {},
                    "reasoning": "Could be fetch but pick is more appropriate for single object move"
                }
            ],
            "needs_clarification": False,
            "raw_entities": [
                {"type": "color", "value": "red", "text": "红色"},
                {"type": "object", "value": "cube", "text": "方块"},
                {"type": "color", "value": "blue", "text": "蓝色"}
            ]
        }
    },
    {
        "input": "去那个桌子",
        "output": {
            "primary_intent": {
                "intent_type": "move_to_workspace",
                "confidence": 0.6,
                "slots": {
                    "workspace_name": "table",
                    "workspace_color": "",
                    "approach_direction": "auto"
                },
                "reasoning": "Vague reference to '那个桌子' (that table), missing color specification"
            },
            "alternative_intents": [],
            "needs_clarification": True,
            "clarification_question": "Which color table would you like me to go to?",
            "raw_entities": [
                {"type": "workspace", "value": "table", "text": "桌子"}
            ]
        }
    },
    {
        "input": "在红色和蓝色桌子之间巡逻两圈",
        "output": {
            "primary_intent": {
                "intent_type": "guard_loop",
                "confidence": 0.93,
                "slots": {
                    "waypoints": [
                        {"workspace_name": "table", "workspace_color": "red"},
                        {"workspace_name": "table", "workspace_color": "blue"}
                    ],
                    "loop_count": 2,
                    "patrol_speed": "normal"
                },
                "reasoning": "Two workspaces mentioned (red table, blue table) with explicit '两圈' (2 loops)"
            },
            "alternative_intents": [],
            "needs_clarification": False,
            "raw_entities": [
                {"type": "color", "value": "red", "text": "红色"},
                {"type": "color", "value": "blue", "text": "蓝色"},
                {"type": "number", "value": 2, "text": "两圈"}
            ]
        }
    },
    {
        "input": "把绿色物品从黄色桌子送到蓝色桌子",
        "output": {
            "primary_intent": {
                "intent_type": "fetch_sku",
                "confidence": 0.94,
                "slots": {
                    "source_workspace_name": "table",
                    "source_workspace_color": "yellow",
                    "target_workspace_name": "table",
                    "target_workspace_color": "blue",
                    "sku_name": "object",
                    "sku_color": "green"
                },
                "reasoning": "Source '黄色桌子' (yellow table), target '蓝色桌子' (blue table), object '绿色物品' (green object)"
            },
            "alternative_intents": [],
            "needs_clarification": False,
            "raw_entities": [
                {"type": "color", "value": "green", "text": "绿色"},
                {"type": "color", "value": "yellow", "text": "黄色"},
                {"type": "color", "value": "blue", "text": "蓝色"}
            ]
        }
    }
]


def build_few_shot_prompt(examples: list[dict] | None = None) -> str:
    """Build a few-shot prompt from examples."""
    examples = examples or FEW_SHOT_EXAMPLES
    
    prompt_parts = ["Here are some examples:\n"]
    
    for i, example in enumerate(examples, 1):
        prompt_parts.append(f"\nExample {i}:")
        prompt_parts.append(f"Input: {example['input']}")
        prompt_parts.append(f"Output: {example['output']}")
    
    return "\n".join(prompt_parts)


def build_parsing_prompt(
    user_input: str,
    include_examples: bool = True,
    context: dict | None = None,
    catalog: NlSemanticCatalog | None = None,
) -> str:
    """Build complete parsing prompt for user input."""
    prompt_parts = [build_system_prompt(catalog)]
    
    if include_examples:
        prompt_parts.append("\n" + build_few_shot_prompt())
    
    prompt_parts.append("\n" + "=" * 50)
    prompt_parts.append("Now parse the following instruction:")
    prompt_parts.append(f"\nInput: {user_input}")
    
    if context:
        prompt_parts.append("\nContext:")
        for key, value in context.items():
            prompt_parts.append(f"  {key}: {value}")
    
    return "\n".join(prompt_parts)
