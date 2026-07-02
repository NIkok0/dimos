#!/usr/bin/env python3
"""Diagnose rosbridge topic subscription issues."""

import os
import sys
import socket
import time

sys.path.insert(0, "/home/miaoli/Projects/dimos")

def check_env():
    """Check environment configuration."""
    print("=" * 60)
    print("Environment Configuration")
    print("=" * 60)
    
    critical_vars = {
        "ROSBRIDGE_GRPC_TARGET": "10.69.6.133:9091",
        "ROS_NAV_SLAM_STATUS_TOPIC": "/slam_status",
        "ROS_NAV_SLAM_STATUS_TOPIC_TYPE": "robot_interfaces/msg/SlamStatus",
        "ROS_NAV_LOCALIZATION_TIMEOUT_S": "5",
    }
    
    print("\nCritical Environment Variables:")
    for var, default in critical_vars.items():
        actual = os.environ.get(var, f"<unset, default={default}>")
        is_default = actual == default or (default in actual and var not in os.environ)
        status = "✓" if not is_default else "⚠ DEFAULT"
        print(f"  {status} {var}={actual}")
    
    # Check .env file loading
    print("\n.env file locations checked:")
    for path in [".env", "dimos/.env", "../.env", "/home/miaoli/Projects/dimos/.env"]:
        exists = os.path.exists(path)
        status = "✓" if exists else "✗"
        print(f"  {status} {path}")
        if exists and "dimos" in path:
            with open(path) as f:
                content = f.read()
                if "ROSBRIDGE_GRPC_TARGET" in content:
                    for line in content.split("\n"):
                        if "ROSBRIDGE_GRPC_TARGET" in line and not line.startswith("#"):
                            print(f"    → Found: {line.strip()}")

def check_network():
    """Check network connectivity to rosbridge."""
    print("\n" + "=" * 60)
    print("Network Connectivity Test")
    print("=" * 60)
    
    target = os.environ.get("ROSBRIDGE_GRPC_TARGET", "10.69.6.133:9091")
    host, port_str = target.rsplit(":", 1)
    port = int(port_str)
    
    print(f"\nTarget: {host}:{port}")
    
    # DNS resolution
    try:
        ip = socket.gethostbyname(host)
        print(f"  ✓ DNS resolved: {host} → {ip}")
    except socket.gaierror as e:
        print(f"  ✗ DNS failed: {e}")
        return
    
    # TCP connection test
    print(f"\nTesting TCP connection to {ip}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    
    try:
        result = sock.connect_ex((ip, port))
        if result == 0:
            print(f"  ✓ TCP connection successful (port {port} open)")
        else:
            print(f"  ✗ TCP connection failed (error code: {result})")
            print(f"    Possible causes:")
            print(f"    - Robot IP is wrong (current: {host})")
            print(f"    - rosbridge_grpc_server not running on robot")
            print(f"    - Firewall blocking port {port}")
            print(f"    - Network unreachable")
    except socket.timeout:
        print(f"  ✗ Connection timeout (5s)")
        print(f"    → Check if robot is powered on and connected")
    except Exception as e:
        print(f"  ✗ Connection error: {e}")
    finally:
        sock.close()

def check_imports():
    """Check if critical modules import successfully."""
    print("\n" + "=" * 60)
    print("Module Import Test")
    print("=" * 60)
    
    tests = [
        ("dimos.core.global_config", "GlobalConfig"),
        ("dimos.agents.rosbridge.session", "RosbridgeSession"),
        ("dimos.agents.rosbridge.navigation.client", "PyRosbridgeNavigationRosClient"),
        ("py_rosbridge", "RosbridgeClient"),
    ]
    
    for module_name, class_name in tests:
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            print(f"  ✓ {module_name}.{class_name}")
        except ImportError as e:
            print(f"  ✗ {module_name}.{class_name}: {e}")
        except Exception as e:
            print(f"  ⚠ {module_name}.{class_name}: {e}")

def simulate_subscription():
    """Simulate topic subscription without actual connection."""
    print("\n" + "=" * 60)
    print("Subscription Simulation (Code Path)")
    print("=" * 60)
    
    try:
        from dimos.agents.rosbridge.navigation.client import PyRosbridgeNavigationRosClient
        from dimos.agents.rosbridge.session import RosbridgeSession
        from dimos.core.global_config import global_config
        
        print("\nConfiguration that would be used:")
        print(f"  rosbridge_grpc_target: {global_config.rosbridge_grpc_target}")
        print(f"  slam_status_topic: {global_config.ros_nav_slam_status_topic}")
        print(f"  slam_status_topic_type: {global_config.ros_nav_slam_status_topic_type}")
        print(f"  topic_timeout_s: {global_config.ros_nav_localization_timeout_s}")
        
        print("\nExpected flow:")
        print("  1. PyRosbridgeNavigationRosClient.get_slam_state() called")
        print("  2. _ensure_subscribed() subscribes to /slam_status")
        print("  3. _latest_message() waits 5s for message from queue")
        print("  4. If no message → queue.Empty → returns 'unavailable'")
        
        print("\n⚠  If colleague's code works but yours doesn't:")
        print("  → Check if you have different .env file in working directory")
        print("  → Check environment variable precedence (env > .env > defaults)")
        
    except Exception as e:
        print(f"  ✗ Failed to load configuration: {e}")

def main():
    print("DimOS Rosbridge Topic Diagnostic Tool")
    print("=" * 60)
    
    check_env()
    check_network()
    check_imports()
    simulate_subscription()
    
    print("\n" + "=" * 60)
    print("Recommendations")
    print("=" * 60)
    print("""
1. Verify robot IP address:
   $ ping 10.69.6.133  (or whatever your robot IP is)
   
2. Check if rosbridge_grpc_server is running on robot:
   (SSH to robot and check process)
   
3. Compare with working environment:
   $ diff <(env | grep DIMOS | sort) <(ssh colleague 'env | grep DIMOS | sort')
   
4. If timeout issues:
   $ export ROS_NAV_LOCALIZATION_TIMEOUT_S=10.0
   
5. Debug subscription:
   $ python scripts/probe_slam_status_grpc.py
    """)

if __name__ == "__main__":
    main()
