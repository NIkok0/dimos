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

"""Dax Agent blueprint.

This module is the production agent entrypoint for natural-language robot tasks. It keeps
the external agent name aligned with the Dax SDK integration direction while reusing the
existing unified NL task execution chain. The blueprint only assembles the task skill,
MCP server, and MCP client; VLA/Dax/ROS details stay behind the ActionPlan orchestrator
and adapter boundary.
"""

import os

from dimos.agents.mcp.mcp_client import McpClient
from dimos.agents.mcp.mcp_server import McpServer
from dimos.agents.dax_agent_system_prompt import DAX_AGENT_SYSTEM_PROMPT
from dimos.agents.skills.chat_bridge_skill import ChatBridgeSkill
from dimos.agents.skills.dax_joint_control_skill import DaxJointControlSkill
from dimos.agents.skills.nl_task_execution_skill import NlTaskExecutionSkill
from dimos.agents.skills.vis_bridge_skill import VisBridgeSkill
from dimos.core.coordination.blueprints import autoconnect

# Default model for Dax Agent
# Can be overridden via DAX_AGENT_MODEL environment variable
# Supported models: deepseek-v4-pro, deepseek-v4-flash, gpt-4o, claude-3-5-sonnet, etc.
_DEFAULT_MODEL = "deepseek-v4-pro"

# Get model from env or use default
_agent_model = os.getenv("DAX_AGENT_MODEL", _DEFAULT_MODEL)

dax_agent = autoconnect(
    NlTaskExecutionSkill.blueprint(),
    DaxJointControlSkill.blueprint(),
    ChatBridgeSkill.blueprint(),
    VisBridgeSkill.blueprint(),
    McpServer.blueprint(),
    McpClient.blueprint(model=_agent_model, system_prompt=DAX_AGENT_SYSTEM_PROMPT),
)

__all__ = ["dax_agent"]
