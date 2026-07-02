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

"""py_rosbridge client for the real robot navigation interfaces.

This client is the concrete lower-body navigation transport for Dax Agent's
``ros_topic`` mode. It talks only to the real robot contracts:
``/slam_status`` and ``/map`` topics plus the ``/navigate_to_pose`` action.
It returns small DimOS dictionaries/results so the higher-level adapter can
keep doing task routing, relative-goal computation, safety checks, and logging.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from typing import Any

from py_rosbridge.codecs import geometry_msgs, nav_msgs, std_msgs  # pyright: ignore[reportMissingImports]

from dimos.agents.navigation_contracts import (
    parse_nav_auto_cancel_status_codes,
    should_auto_cancel_nav_status,
)
from dimos.agents.rosbridge.codecs.robot_interfaces import (
    NavStatusCodec,
    NavigateToPoseFeedbackCodec,
    NavigateToPoseGoal,
    NavigateToPoseGoalCodec,
    NavigateToPoseResultCodec,
    SlamStatusCodec,
)
from dimos.agents.ros_topic_navigation_adapter import NavigateToPoseActionResult
from dimos.agents.rosbridge.qos_profiles import (
    MAP_TOPIC_QOS,
    NAV_STATUS_TOPIC_QOS,
    SLAM_STATUS_TOPIC_QOS,
)
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.core.global_config import GlobalConfig, global_config
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


def planar_yaw_from_slam_message(msg: Any) -> float:
    """Convert SlamStatus.angle to map-frame ROS yaw (CCW from +X).

    Dax publishes ``angle`` as heading measured from map +Y (north) toward +X
    (east), not REP-103 yaw from +X.  Relative goals and map arrows must use
    the converted value, not ``angle`` directly in ``cos/sin``.
    """
    angle = float(msg.angle)
    return math.atan2(math.cos(angle), math.sin(angle))


class PyRosbridgeNavigationRosClient:
    """Read real navigation topics and send NavigateToPose action goals."""

    def __init__(
        self,
        *,
        session: RosbridgeSession,
        slam_status_topic: str,
        slam_status_topic_type: str,
        map_topic: str,
        map_topic_type: str,
        nav_status_topic: str,
        nav_status_topic_type: str,
        navigate_action: str,
        navigate_action_type: str,
        timeout_s: float,
        topic_timeout_s: float,
        auto_cancel_enabled: bool = True,
        auto_cancel_status_codes: frozenset[int] | None = None,
        auto_cancel_poll_s: float = 0.2,
        auto_cancel_wait_s: float = 10.0,
    ) -> None:
        self._session = session
        self._slam_status_topic = slam_status_topic
        self._slam_status_topic_type = slam_status_topic_type
        self._map_topic = map_topic
        self._map_topic_type = map_topic_type
        self._nav_status_topic = nav_status_topic
        self._nav_status_topic_type = nav_status_topic_type
        self._navigate_action = navigate_action
        self._navigate_action_type = navigate_action_type
        self._timeout_s = timeout_s
        self._topic_timeout_s = topic_timeout_s
        self._auto_cancel_enabled = auto_cancel_enabled
        self._auto_cancel_status_codes = auto_cancel_status_codes or frozenset({1005, 1006, 1007})
        self._auto_cancel_poll_s = auto_cancel_poll_s
        self._auto_cancel_wait_s = auto_cancel_wait_s
        self._slam_messages: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._map_messages: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._nav_status_messages: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._latest_map_message: Any | None = None
        self._subscribed = False
        self._active_handle_lock = threading.Lock()
        self._active_handle: Any | None = None

    @classmethod
    def from_config(
        cls,
        config: GlobalConfig | None = None,
        *,
        session: RosbridgeSession | None = None,
    ) -> PyRosbridgeNavigationRosClient:
        """Build the client from DimOS real navigation configuration."""
        cfg = config or global_config
        return cls(
            session=session or RosbridgeSession.from_config(cfg),
            slam_status_topic=cfg.ros_nav_slam_status_topic,
            slam_status_topic_type=cfg.ros_nav_slam_status_topic_type,
            map_topic=cfg.ros_nav_map_topic,
            map_topic_type=cfg.ros_nav_map_topic_type,
            nav_status_topic=cfg.ros_nav_status_topic,
            nav_status_topic_type=cfg.ros_nav_status_topic_type,
            navigate_action=cfg.ros_navigate_to_pose_action,
            navigate_action_type=cfg.ros_navigate_to_pose_action_type,
            timeout_s=cfg.ros_nav_action_timeout_s,
            topic_timeout_s=cfg.ros_nav_localization_timeout_s,
            auto_cancel_enabled=cfg.ros_nav_auto_cancel_enabled,
            auto_cancel_status_codes=parse_nav_auto_cancel_status_codes(
                cfg.ros_nav_auto_cancel_status_codes
            ),
            auto_cancel_poll_s=cfg.ros_nav_auto_cancel_poll_s,
            auto_cancel_wait_s=cfg.ros_nav_auto_cancel_wait_s,
        )

    def get_slam_state(self) -> dict[str, Any]:
        """Return the latest SLAM/localization state from ``/slam_status``.

        Retries briefly on first subscription to handle network round-trip delay.
        """
        self._ensure_subscribed()
        # Retry briefly for initial subscription latency
        retries = 3
        for attempt in range(retries):
            try:
                msg = self._latest_message(self._slam_messages)
                pose = msg.pose
                quaternion_yaw = _yaw_from_quaternion(pose.orientation)
                return {
                    "status": msg.status,
                    "pose": {
                        "frame_id": msg.header.frame_id or "map",
                        "x": float(pose.position.x),
                        "y": float(pose.position.y),
                        "yaw": planar_yaw_from_slam_message(msg),
                    },
                    "raw": {
                        "status": msg.status,
                        "score": msg.score,
                        "process": msg.process,
                        "relocated": msg.relocated,
                        "angle": msg.angle,
                        "quaternion_yaw": quaternion_yaw,
                    },
                }
            except queue.Empty:
                if attempt < retries - 1:
                    time.sleep(0.1)
                    continue
                # Final attempt failed
                logger.info(
                    "SLAM status unavailable",
                    topic=self._slam_status_topic,
                    timeout_s=self._topic_timeout_s,
                    retries=retries,
                )
                # Force re-subscription on next call in case connection dropped
                self._subscribed = False
                logger.debug("Reset subscription flag for next retry")
                return {
                    "status": "unavailable",
                    "pose": {},
                    "raw": {
                        "reason": "slam_status_timeout",
                        "topic": self._slam_status_topic,
                        "timeout_s": self._topic_timeout_s,
                    },
                }

    def get_occupancy_grid(self) -> nav_msgs.OccupancyGrid | None:
        """Return the latest OccupancyGrid from ``/map``, or None if unavailable.

        For TRANSIENT_LOCAL topics, the publisher sends the last message immediately
        upon subscription, but there may be a small delay for network round-trip.
        We retry briefly to allow the retained message to arrive.
        """
        self._ensure_subscribed()
        if self._latest_map_message is not None:
            return self._latest_map_message

        # TRANSIENT_LOCAL messages may need a moment to arrive after subscription.
        # Retry briefly before giving up.
        retries = 3
        for attempt in range(retries):
            try:
                self._latest_map_message = self._latest_message(self._map_messages)
                return self._latest_map_message
            except queue.Empty:
                if attempt < retries - 1:
                    time.sleep(0.1)  # Short wait for TRANSIENT_LOCAL message to arrive
                continue

        logger.info(
            "OccupancyGrid unavailable",
            topic=self._map_topic,
            timeout_s=self._topic_timeout_s,
            retries=retries,
        )
        return None

    def send_navigate_to_pose(
        self,
        goal: dict[str, Any],
        *,
        timeout_s: float,
        request_id: str = "",
    ) -> NavigateToPoseActionResult:
        """Send one real ``/navigate_to_pose`` action goal and wait for result."""
        self._ensure_subscribed()
        goal_log = _navigation_action_goal_log(goal)
        t0 = time.monotonic()
        logger.info(
            "Navigation action send",
            request_id=request_id or None,
            action=self._navigate_action,
            action_type=self._navigate_action_type,
            grpc_target=self._session.target,
            timeout_s=timeout_s,
            goal=goal_log,
        )
        handle: Any | None = None
        auto_cancel_trigger: dict[str, Any] | None = None
        try:
            pose = goal.get("pose", {})
            nav_goal = NavigateToPoseGoal(
                pose=_pose_stamped_from_goal_pose(pose),
                behavior_tree=str(goal.get("behavior_tree", "")),
            )
            handle = self._session.get_client().send_action_goal(
                self._navigate_action,
                self._navigate_action_type,
                nav_goal,
                goal_codec=NavigateToPoseGoalCodec,
                feedback_codec=NavigateToPoseFeedbackCodec,
                result_codec=NavigateToPoseResultCodec,
                timeout_sec=timeout_s,
                wait_accepted_timeout=timeout_s,
            )
            with self._active_handle_lock:
                self._active_handle = handle
            event, auto_cancel_trigger = self._wait_for_action_result(
                handle,
                timeout_s=timeout_s,
                request_id=request_id,
                goal_log=goal_log,
            )
            result = event.result
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.info(
                "Navigation action done",
                request_id=request_id or None,
                action=self._navigate_action,
                duration_ms=round(elapsed_ms, 1),
                goal_id=str(event.goal_id),
                result_code=int(result.result_code),
                result_message=str(result.result_message),
                action_status=int(event.status),
                auto_cancelled=auto_cancel_trigger is not None,
                goal=goal_log,
            )
            nav_status_code = None
            nav_description = ""
            raw: dict[str, Any] = {
                "action": event.action,
                "action_type": event.type,
                "action_status": int(event.status),
            }
            if auto_cancel_trigger is not None:
                nav_status_code = int(auto_cancel_trigger["status_code"])
                nav_description = str(auto_cancel_trigger.get("description", ""))
                raw["auto_cancelled"] = True
                raw["auto_cancel_trigger_code"] = nav_status_code
            return NavigateToPoseActionResult(
                result_code=int(result.result_code),
                result_message=str(result.result_message),
                result_pose=_pose_stamped_to_dict(result.result_pose),
                uuid=str(event.goal_id),
                nav_status_code=nav_status_code,
                nav_description=nav_description,
                raw=raw,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.info(
                "Navigation action failed",
                request_id=request_id or None,
                action=self._navigate_action,
                duration_ms=round(elapsed_ms, 1),
                goal=goal_log,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        finally:
            with self._active_handle_lock:
                self._active_handle = None

    def _wait_for_action_result(
        self,
        handle: Any,
        *,
        timeout_s: float,
        request_id: str,
        goal_log: dict[str, Any],
    ) -> tuple[Any, dict[str, Any] | None]:
        """Poll NavStatus while waiting; auto-cancel on configured status codes."""
        deadline = time.monotonic() + timeout_s
        auto_cancel_trigger: dict[str, Any] | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"navigation timed out after {timeout_s}s")

            if handle._result_future.done():  # noqa: SLF001
                return handle.result(timeout=remaining), auto_cancel_trigger

            if self._auto_cancel_enabled:
                nav_status = self._try_latest_nav_status()
                if nav_status is not None and should_auto_cancel_nav_status(
                    int(nav_status.status_code),
                    allowed=self._auto_cancel_status_codes,
                ):
                    trigger_code = int(nav_status.status_code)
                    auto_cancel_trigger = {
                        "status_code": trigger_code,
                        "description": str(getattr(nav_status, "description", "")),
                    }
                    logger.info(
                        "Navigation auto-cancel triggered",
                        request_id=request_id or None,
                        action=self._navigate_action,
                        nav_status_code=trigger_code,
                        nav_description=auto_cancel_trigger["description"],
                        goal=goal_log,
                    )
                    handle.cancel(timeout=self._auto_cancel_wait_s)
                    return handle.result(timeout=self._auto_cancel_wait_s), auto_cancel_trigger

            time.sleep(min(self._auto_cancel_poll_s, remaining))

    def _try_latest_nav_status(self) -> Any | None:
        """Return the newest cached NavStatus message without blocking."""
        latest: Any | None = None
        while True:
            try:
                latest = self._nav_status_messages.get_nowait()
            except queue.Empty:
                return latest

    def _cache_slam_status(self, event: Any) -> None:
        """Cache one decoded ``/slam_status`` message from a py_rosbridge event."""
        self._replace_latest(self._slam_messages, event.message)

    def _cache_occupancy_grid(self, event: Any) -> None:
        """Cache one decoded ``/map`` OccupancyGrid message from a py_rosbridge event."""
        self._latest_map_message = event.message
        self._replace_latest(self._map_messages, event.message)

    def _cache_nav_status(self, event: Any) -> None:
        """Cache one decoded ``/navigation_current_status`` message."""
        self._replace_latest(self._nav_status_messages, event.message)

    def _ensure_subscribed(self) -> None:
        """Subscribe once to the real navigation topics and cache incoming messages."""
        if self._subscribed:
            return
        client = self._session.get_client()
        client.subscribe(
            self._slam_status_topic,
            self._slam_status_topic_type,
            self._cache_slam_status,
            codec=SlamStatusCodec,
            qos=SLAM_STATUS_TOPIC_QOS,
        )
        client.subscribe(
            self._map_topic,
            self._map_topic_type,
            self._cache_occupancy_grid,
            codec=nav_msgs.OccupancyGridCodec,
            qos=MAP_TOPIC_QOS,
        )
        client.subscribe(
            self._nav_status_topic,
            self._nav_status_topic_type,
            self._cache_nav_status,
            codec=NavStatusCodec,
            qos=NAV_STATUS_TOPIC_QOS,
        )
        self._subscribed = True

    def _replace_latest(self, messages: queue.Queue[Any], message: Any) -> None:
        """Keep only the freshest topic message so navigation reads never lag."""
        try:
            messages.put_nowait(message)
            return
        except queue.Full:
            pass
        try:
            messages.get_nowait()
        except queue.Empty:
            pass
        messages.put_nowait(message)

    def _latest_message(self, messages: queue.Queue[Any]) -> Any:
        """Wait for one message and drain the queue to return the newest value."""
        latest = messages.get(timeout=self._topic_timeout_s)
        while True:
            try:
                latest = messages.get_nowait()
            except queue.Empty:
                return latest


def _navigation_action_goal_log(goal: dict[str, Any]) -> dict[str, Any]:
    """Return a compact goal payload safe for structured run logs."""
    pose = goal.get("pose", {})
    if not isinstance(pose, dict):
        pose = {}
    return {
        "workspace_id": str(goal.get("workspace_id", "")),
        "pose": {
            "frame_id": str(pose.get("frame_id", "map")),
            "x": float(pose.get("x", 0.0)),
            "y": float(pose.get("y", 0.0)),
            "yaw": float(pose.get("yaw", 0.0)),
        },
        "behavior_tree": str(goal.get("behavior_tree", "")),
    }


def _pose_stamped_from_goal_pose(pose: dict[str, Any]) -> geometry_msgs.PoseStamped:
    """Convert DimOS goal metadata into a geometry_msgs/PoseStamped dataclass."""
    yaw = float(pose.get("yaw", 0.0))
    return geometry_msgs.PoseStamped(
        header=std_msgs.Header(frame_id=str(pose.get("frame_id", "map"))),
        pose=geometry_msgs.Pose(
            position=geometry_msgs.Point(
                x=float(pose.get("x", 0.0)),
                y=float(pose.get("y", 0.0)),
                z=float(pose.get("z", 0.0)),
            ),
            orientation=_quaternion_from_yaw(yaw),
        ),
    )


def _pose_stamped_to_dict(pose: geometry_msgs.PoseStamped) -> dict[str, Any]:
    """Convert a geometry_msgs/PoseStamped dataclass into compact metadata."""
    return {
        "frame_id": pose.header.frame_id,
        "x": float(pose.pose.position.x),
        "y": float(pose.pose.position.y),
        "z": float(pose.pose.position.z),
        "yaw": _yaw_from_quaternion(pose.pose.orientation),
    }


def _quaternion_from_yaw(yaw: float) -> geometry_msgs.Quaternion:
    """Build a planar quaternion from yaw in radians."""
    half = yaw / 2.0
    return geometry_msgs.Quaternion(z=math.sin(half), w=math.cos(half))


def _yaw_from_quaternion(quaternion: geometry_msgs.Quaternion) -> float:
    """Extract planar yaw from a geometry_msgs quaternion."""
    siny_cosp = 2.0 * (
        float(quaternion.w) * float(quaternion.z)
        + float(quaternion.x) * float(quaternion.y)
    )
    cosy_cosp = 1.0 - 2.0 * (
        float(quaternion.y) * float(quaternion.y)
        + float(quaternion.z) * float(quaternion.z)
    )
    return math.atan2(siny_cosp, cosy_cosp)


__all__ = ["PyRosbridgeNavigationRosClient", "planar_yaw_from_slam_message"]
