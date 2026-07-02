# robot_interfaces/msg/NavStatus — sync from真机: ros2 interface show robot_interfaces/msg/NavStatus
int32 NAV_UNKNNOWN=-1
int32 NAV_IDLE=0
int32 NAV_RECEIVE_TARGETS=1000
int32 NAV_GLOBAL_PATH_SUCCESS=1001
int32 NAV_MOVING=1002
int32 NAV_SUCCESS=1003
int32 NAV_CALCLED=1004
int32 NAV_PREEMPTED=1005
int32 NAV_PATH_IS_BLOCKED=1006
int32 NAV_RECOVERY=2000
int32 NAV_FAILURE=3000
int32 NAV_GLOBAL_PATH_FAILURE=3001
int32 NAV_MOVING_FAILURE=3002

float64 timestamp
int32 status_code
string description
uint8[] uuid
