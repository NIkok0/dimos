# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PICK_COMBOS = {
    "blue": ("red", "yellow", "green"),
    "red": ("yellow", "blue", "green"),
    "green": ("yellow", "blue", "red"),
}
TABLE_ZH = {"blue": "蓝色", "red": "红色", "green": "绿色"}
TABLE_SHORT_ZH = {"blue": "蓝", "red": "红", "green": "绿"}
SKU_ZH = {"blue": "蓝色", "red": "红色", "green": "绿色", "yellow": "黄色"}
SKU_SHORT_ZH = {"blue": "蓝", "red": "红", "green": "绿", "yellow": "黄"}
CN_LOOP = {1: "一圈", 2: "两圈", 3: "三圈"}
EN_LOOP = {1: "one loop", 2: "two loops", 3: "three loops"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="output/task_generation_eval_600.jsonl",
        help="Path to write dataset (suffix .json -> JSON array, .jsonl -> JSONL).",
    )
    parser.add_argument(
        "--format",
        choices=("json", "jsonl", "auto"),
        default="auto",
        help="Output format: json (array), jsonl (one per line), auto (infer from --output suffix).",
    )
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    records.extend(_pick_records())
    records.extend(_fetch_records())
    records.extend(_guard_records())
    records.extend(_nav_records())
    records.extend(_negative_records())

    for index, record in enumerate(records, 1):
        record["id"] = f"eval_task_{index:04d}"

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fmt = args.format
    if fmt == "auto":
        fmt = "json" if output.suffix.lower() == ".json" else "jsonl"

    if fmt == "json":
        payload = json.dumps(records, ensure_ascii=False, indent=2)
    else:
        payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    output.write_text(payload, encoding="utf-8")
    print(f"Wrote {len(records)} rows to {output} (format={fmt})")


def _pick_records() -> list[dict[str, Any]]:
    templates = [
        "去{table}桌子抓{sku}方块",
        "请去{table}桌面拿取{sku}cube",
        "移动到{table}工作台，抓取{sku}立方体",
        "帮我抓{table_short}桌上的{sku_short}方块",
        "在{table}table上拿{sku}cube",
        "到{table}桌子取{sku}方块",
        "去{table}工作台pick {sku_en} cube",
        "请移动到{table}桌子并抓取{sku}方块",
        "pick the {sku_en} cube on the {table_en} table",
        "go to the {table_en} table and pick the {sku_en} cube",
        "pick up the {sku_en} cube from the {table_en} table",
        "move to the {table_en} table and pick up the {sku_en} cube",
    ]
    rows = []
    for table_color, sku_colors in PICK_COMBOS.items():
        for sku_color in sku_colors:
            for template in templates:
                rows.append(
                    _ok_record(
                        template.format(
                            table=TABLE_ZH[table_color],
                            table_short=TABLE_SHORT_ZH[table_color],
                            table_en=table_color,
                            sku=SKU_ZH[sku_color],
                            sku_short=SKU_SHORT_ZH[sku_color],
                            sku_en=sku_color,
                        ),
                        "pick_sku",
                        {
                            "workspace_name": "table",
                            "workspace_color": table_color,
                            "sku_name": "cube",
                            "sku_color": sku_color,
                        },
                        _pick_plan(table_color, sku_color),
                    )
                )
    return rows


def _fetch_records() -> list[dict[str, Any]]:
    templates = [
        "把{source}桌子的{sku}方块拿到{target}桌子",
        "把{source}桌子的{sku}cube送到{target}桌子",
        "移动到{source}桌子拿{sku}方块，再移动到{target}桌子放下",
        "从{source}table取{sku}cube到{target}table",
        "请完成fetch：{source}桌子{sku}方块到{target}桌子",
        "拿{source}桌面上的{sku}立方体到{target}桌面",
        "先去{source}桌子抓{sku}方块，再去{target}桌子放下",
        "从{source}桌子拿{sku}方块放到{target}桌子",
        "把{source_short}桌上的{sku_short}方块送到{target_short}桌",
        "fetch the {sku_en} cube from the {source_en} table to the {target_en} table",
        "relocate the {sku_en} cube from the {source_en} table to the {target_en} table",
        "go to the {source_en} table, pick the {sku_en} cube, "
        "then go to the {target_en} table and drop it",
        "move to the {source_en} table, take the {sku_en} cube, "
        "move to the {target_en} table, drop it",
    ]
    rows = []
    for source, sku_colors in PICK_COMBOS.items():
        for sku_color in sku_colors:
            for target in PICK_COMBOS:
                if target == source:
                    continue
                for template in templates:
                    rows.append(
                        _ok_record(
                            template.format(
                                source=TABLE_ZH[source],
                                source_short=TABLE_SHORT_ZH[source],
                                source_en=source,
                                target=TABLE_ZH[target],
                                target_short=TABLE_SHORT_ZH[target],
                                target_en=target,
                                sku=SKU_ZH[sku_color],
                                sku_short=SKU_SHORT_ZH[sku_color],
                                sku_en=sku_color,
                            ),
                            "fetch_sku",
                            {
                                "source_workspace_name": "table",
                                "source_workspace_color": source,
                                "target_workspace_name": "table",
                                "target_workspace_color": target,
                                "sku_name": "cube",
                                "sku_color": sku_color,
                            },
                            _fetch_plan(source, sku_color, target),
                        )
                    )
    return rows


def _guard_records() -> list[dict[str, Any]]:
    templates = [
        "在{first}桌子和{second}桌子之间巡逻{loop_cn}",
        "守卫{first}桌子和{second}桌子{loop_cn}",
        "在{first}工作台和{second}工作台之间巡逻{loop_cn}",
        "请在{first}桌和{second}桌之间巡逻{loop_cn}",
        "做guard：{first}桌子到{second}桌子{loop_cn}",
        "做patrol：{first}工作台到{second}工作台{loop_cn}",
        "guard the {first_en} table and {second_en} table for {loop_en}",
        "patrol between the {first_en} table and {second_en} table {loop_en}",
        "guard loop: {first_en} table to {second_en} table, {loop_en}",
        "run a guard loop between the {first_en} table and {second_en} table for {loop_en}",
    ]
    rows = []
    colors = ("blue", "red", "green")
    for first in colors:
        for second in colors:
            if first == second:
                continue
            for loop_count in (1, 2, 3):
                for template in templates:
                    rows.append(
                        _ok_record(
                            template.format(
                                first=TABLE_ZH[first],
                                second=TABLE_ZH[second],
                                first_en=first,
                                second_en=second,
                                loop_cn=CN_LOOP[loop_count],
                                loop_en=EN_LOOP[loop_count],
                            ),
                            "guard_loop",
                            {
                                "waypoints": [
                                    {"workspace_name": "table", "workspace_color": first},
                                    {"workspace_name": "table", "workspace_color": second},
                                ],
                                "loop_count": loop_count,
                            },
                            _guard_plan(first, second, loop_count),
                        )
                    )
    return rows


def _nav_records() -> list[dict[str, Any]]:
    from dimos.agents.nl.navigation_semantic_catalog import (
        DEFAULT_NL_SEMANTICS_PATH,
        NavigationSemanticCatalog,
    )

    catalog = NavigationSemanticCatalog.from_file(DEFAULT_NL_SEMANTICS_PATH)
    rows: list[dict[str, Any]] = []

    direction_samples = {
        "backward": ("向后", "backward"),
        "forward": ("向前", "forward"),
        "left": ("向左", "left"),
        "right": ("向右", "right"),
    }
    relative_templates = catalog.eval_templates.get("move_relative", [])
    if isinstance(relative_templates, list):
        for direction, (direction_alias, direction_en) in direction_samples.items():
            for template in relative_templates:
                if not isinstance(template, str):
                    continue
                text = template.format(
                    direction=direction_alias,
                    direction_alias=direction_alias,
                    direction_en=direction_en,
                    distance=1,
                )
                distance_units = 20.0
                if "0.5" in text or "0.5m" in text:
                    distance_units = 10.0
                if "三格" in text:
                    distance_units = 3.0
                if "1格" in text:
                    distance_units = 1.0
                if "2格" in text:
                    distance_units = 2.0
                if "3格" in text or "三格" in text:
                    distance_units = 3.0
                rows.append(
                    _ok_record(
                        text,
                        "move_relative",
                        {"direction": direction, "distance_units": distance_units},
                        {
                            "intent_type": "move_relative",
                            "template": "move_relative_template",
                            "steps": [
                                {
                                    "executor": "sys_navigation",
                                    "action_type": "move_relative",
                                }
                            ],
                        },
                    )
                )

    workspace_samples = [
        ("移动到前方固定工作区", "front_workspace", "", "move_to_workspace"),
        ("前往前方工作区", "front_workspace", "", "move_to_workspace"),
        ("go to front_workspace", "front_workspace", "", "move_to_workspace"),
        ("前往红色桌子", "table", "red", "move_to_workspace"),
        ("移动到蓝色桌子", "table", "blue", "move_to_workspace"),
        ("go to the green table", "table", "green", "move_to_workspace"),
    ]
    for text, workspace_name, workspace_color, intent in workspace_samples:
        rows.append(
            _ok_record(
                text,
                intent,
                {
                    "workspace_name": workspace_name,
                    "workspace_color": workspace_color,
                },
                {
                    "intent_type": intent,
                    "template": f"{intent}_template",
                    "steps": [
                        {
                            "executor": "sys_navigation",
                            "action_type": intent,
                        }
                    ],
                },
            )
        )

    move_ws_templates = catalog.eval_templates.get("move_to_workspace", [])
    if isinstance(move_ws_templates, list):
        color_samples = [
            ("red", "红色", "red"),
            ("blue", "蓝色", "blue"),
            ("green", "绿色", "green"),
        ]
        triggers = catalog.movement_triggers[:3]
        for color_en, color_nl, canonical in color_samples:
            for trigger in triggers:
                for template in move_ws_templates:
                    if not isinstance(template, str):
                        continue
                    if "{color_en}" not in template and "{workspace_alias}" not in template:
                        continue
                    text = template.format(
                        movement_trigger=trigger,
                        workspace_alias=f"{color_nl}桌子",
                        color_en=color_en,
                        color_nl=color_nl,
                    )
                    rows.append(
                        _ok_record(
                            text,
                            "move_to_workspace",
                            {
                                "workspace_name": "table",
                                "workspace_color": canonical,
                            },
                            {
                                "intent_type": "move_to_workspace",
                                "template": "move_to_workspace_template",
                                "steps": [
                                    {
                                        "executor": "sys_navigation",
                                        "action_type": "move_to_workspace",
                                    }
                                ],
                            },
                        )
                    )

    return rows


def _negative_records() -> list[dict[str, Any]]:
    negatives = [
        ("抓红色方块", "NEED_CLARIFICATION", "missing workspace color"),
        ("去蓝色桌子抓方块", "NEED_CLARIFICATION", "missing sku color"),
        ("去蓝色桌子擦桌面", "UNSUPPORTED_INTENT", "unsupported action"),
        ("把蓝色桌子的红色方块拿走", "NEED_CLARIFICATION", "fetch missing target"),
        ("把蓝色桌子的红色方块拿到桌子", "NEED_CLARIFICATION", "fetch missing target color"),
        ("在蓝色桌子和绿色桌子之间巡逻", "NEED_CLARIFICATION", "guard missing loop count"),
        ("guard the blue table", "NEED_CLARIFICATION", "guard missing waypoint/loop"),
        ("去黄色桌子抓红色方块", "INVALID_SLOT", "invalid workspace color"),
        ("去蓝色桌子抓蓝色方块", "INVALID_SLOT", "untrusted same-color pick"),
        ("turn on the kitchen light", "UNSUPPORTED_INTENT", "non-robot task"),
    ]
    return [
        {
            "text": text,
            "expected_status": "fail",
            "expected_error_code": error_code,
            "note": note,
        }
        for text, error_code, note in negatives
        for _ in range(4)
    ]


def _ok_record(
    text: str,
    intent: str,
    slots: dict[str, Any],
    action_plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "text": text,
        "expected_status": "ok",
        "expected_intent": intent,
        "expected_slots": slots,
        "expected_action_plan": action_plan,
    }


def _pick_plan(table_color: str, sku_color: str) -> dict[str, Any]:
    return {
        "intent_type": "pick_sku",
        "template": "pick_sku_template",
        "steps": [
            {"executor": "sys_navigation", "action_type": "move_to_workspace"},
            {"executor": "vla", "action_type": "vla_pick_sku"},
        ],
    }


def _fetch_plan(source: str, sku_color: str, target: str) -> dict[str, Any]:
    return {
        "intent_type": "fetch_sku",
        "template": "fetch_sku_template",
        "steps": [
            {"executor": "sys_navigation", "action_type": "move_to_workspace"},
            {"executor": "vla", "action_type": "vla_pick_sku"},
            {"executor": "sys_navigation", "action_type": "move_to_workspace"},
            {"executor": "vla", "action_type": "vla_drop_sku"},
        ],
    }


def _guard_plan(first: str, second: str, loop_count: int) -> dict[str, Any]:
    return {
        "intent_type": "guard_loop",
        "template": "guard_loop_template",
        "steps": [
            {"executor": "sys_navigation", "action_type": "move_to_workspace"}
            for _ in range(loop_count * 2)
        ],
    }


if __name__ == "__main__":
    main()
