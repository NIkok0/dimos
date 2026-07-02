# DimOS NL 解析架构 v2.0 (LLM-Driven)

**架构原则**: LLM 为主解析器，catalog/mapper 为 slot 校验与归一化层（规则 parser 不进入生产路由）

---

## 架构概览

```
User Input (NL)
      ↓
LLMIntentParser (primary)
      ↓
CatalogSlotValidator (normalize + validate slots)
      ↓
nl_intent_bridge → TaskIntent
```

Legacy diagram (rule-first) is deprecated. Default config:

```python
HybridRouterConfig(
    llm_as_primary=True,
    use_llm_fallback=False,
    validate_llm_with_rules=False,
)
```

---

## 组件说明

### 1. LLM Parser (`nl/llm/parser.py`)

**职责**: 使用 LLM 进行意图识别和槽位提取

**输入**: 用户自然语言指令
**输出**: `ParseResult` (intent_type, slots, confidence)

**实现**:
- 使用 LangChain + OpenAI/Anthropic API
- 结构化输出 (Pydantic schema)
- 支持少样本学习 (few-shot prompting)

```python
from dimos.agents.nl.llm.parser import LLMIntentParser

parser = LLMIntentParser(model="gpt-4o")
result = parser.parse("抓取红色方块放到蓝色桌子上")

# result.intent_type == "pick_sku"
# result.slots == {
#     "workspace_type": "table",
#     "table_color": "red",
#     "object_type": "cube",
#     "object_color": "red",
#     "goal_workspace_type": "table",
#     "goal_table_color": "blue",
# }
```

### 2. Hybrid Router (`nl/core/hybrid_router.py`)

**职责**: 协调规则和 LLM 解析器，选择最佳结果

**配置**:
```python
HybridRouterConfig(
    rule_confidence_threshold=0.8,  # 规则高于此值直接信任
    llm_fallback_threshold=0.6,     # 低于此值尝试 LLM
    use_llm_fallback=True,          # 启用 LLM fallback
    llm_as_primary=False,           # 规则优先策略
)
```

### 3. Rule Parsers (Fast Path)

**职责**: 快速解析常见模式，作为 LLM 的替代/验证

适用场景:
- "向后移动1米" → 规则解析 (< 1ms)
- "前进两步" → 规则解析 (< 1ms)
- 复杂指令 → LLM 解析 (~500ms)

### 4. VLA Pick Semantic Mapping (Validation Layer)

**职责**: 验证 LLM 提取的 slots 是否与原文一致

流程:
1. LLM 提取候选 slots (candidate_workspace_type, candidate_table_color, ...)
2. `parse_pick_instruction` 验证 slots 是否与原文证据一致
3. 不一致时返回 `NEED_CLARIFICATION`

---

## 数据流示例

### 示例 1: 简单指令 (规则快速路径)

```
用户: "向后移动1米"

规则层:
  - PatternParser matches "向后" + "1米"
  - confidence = 0.95
  - Result: move_relative, direction=backward, distance=20 units

Hybrid Router:
  - Rule confidence (0.95) >= threshold (0.8)
  - Use rule result directly
  - No LLM call needed

输出: TaskIntent("move_relative", slots={...})
```

### 示例 2: 复杂指令 (LLM 解析)

```
用户: "把左边那个红色的东西拿到右边蓝色的台子上"

规则层:
  - Multiple patterns match with low confidence
  - Best match: fetch_sku, confidence = 0.4

Hybrid Router:
  - Rule confidence (0.4) < fallback threshold (0.6)
  - Call LLM parser

LLM 层:
  Prompt: System prompt + few-shot examples + user input
  Output: {
    "intent_type": "fetch_sku",
    "slots": {
      "source_workspace_color": "red",
      "target_workspace_color": "blue",
      "sku_color": "red"
    },
    "confidence": 0.92
  }

Hybrid Router:
  - LLM confidence (0.92) > best rule (0.4)
  - Use LLM result

输出: TaskIntent("fetch_sku", slots={...})
```

### 示例 3: 需要澄清

```
用户: "去那个桌子"

规则层:
  - Matches move_to_workspace, confidence = 0.6
  - Missing workspace_color

Hybrid Router:
  - Confidence < threshold, try LLM

LLM 层:
  Output: {
    "intent_type": "move_to_workspace",
    "slots": {"workspace_name": "table"},
    "confidence": 0.7,
    "needs_clarification": true,
    "clarification_question": "Which color table?"
  }

输出: SkillResult(NEED_CLARIFICATION, "Which color table?")
```

---

## Prompt 设计

### System Prompt 结构

```
You are a natural language parser for a mobile manipulation robot.

## Available Intent Types
1. move_relative - Move in a relative direction
2. move_to_workspace - Navigate to named workspace
3. pick_sku - Pick up object from workspace
4. fetch_sku - Fetch and deliver object
5. guard_loop - Patrol between waypoints

## Parsing Guidelines
- Extract all relevant slots
- Use sensible defaults when info missing
- Support both Chinese and English
- Mark ambiguous instructions for clarification

## Response Format
Respond with JSON matching NLUnderstandingResult schema:
{
  "primary_intent": {
    "intent_type": "...",
    "confidence": 0.0-1.0,
    "slots": {...},
    "reasoning": "..."
  },
  "needs_clarification": true/false,
  "clarification_question": "..."
}
```

### Few-Shot Examples

见 `nl/llm/prompts.py` 中的 `FEW_SHOT_EXAMPLES`

---

## 性能优化

| 优化策略 | 效果 |
|----------|------|
| 规则快速路径 | 简单指令 < 1ms |
| LLM 缓存 | 重复查询命中缓存 |
| 批量 LLM 调用 | 并行处理多个指令 |
| 置信度阈值 | 减少不必要的 LLM 调用 |

---

## 使用方式

### 方式 1: 规则优先 (默认)

```python
from dimos.agents.nl.core.hybrid_router import create_hybrid_router

router = create_hybrid_router(
    llm_model="gpt-4o",
    rule_confidence_threshold=0.8,
    llm_fallback_threshold=0.6,
)

decision = router.route("向后移动1米")
# Uses rule parser (fast)

decision = router.route("把红色方块从蓝色桌子拿到绿色桌子")
# Rules fail → LLM fallback → success
```

### 方式 2: LLM 优先

```python
from dimos.agents.nl.core.hybrid_router import HybridIntentRouter, HybridRouterConfig

router = HybridIntentRouter(
    registry=registry,
    hybrid_config=HybridRouterConfig(
        llm_as_primary=True,
        validate_llm_with_rules=True,
    ),
)

decision = router.route("抓取红色方块")
# LLM first → validation → result
```

---

## 与旧架构对比

| 维度 | 旧架构 | 新架构 |
|------|--------|--------|
| 主解析器 | 规则匹配 (739 行) | LLM + 规则快速路径 |
| 复杂指令 | 难以扩展 | LLM 自然处理 |
| 简单指令 | 规则 (< 1ms) | 规则 (< 1ms) |
| 新增意图 | 改 5 处代码 | 改 prompt + schema |
| 多语言 | 硬编码关键词 | LLM 原生支持 |
| 模糊指令 | NEED_CLARIFICATION | LLM 推理 + 澄清 |

---

## 后续优化方向

1. **Prompt 优化**: A/B 测试不同 prompt 提升准确率
2. **少样本学习**: 动态选择最相关的 examples
3. **LLM 缓存**: 缓存相似查询结果
4. **多轮对话**: 维护对话状态用于上下文解析
5. **模型微调**: 针对机器人指令微调专用模型
