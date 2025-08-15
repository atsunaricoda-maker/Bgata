#!/bin/bash
set -euo pipefail

# AI Drive FUSE Mount Management Script
# This script manages the mount daemon lifecycle (start/stop/status)

# Check if running as root, if not, re-run with sudo
if [[ $EUID -ne 0 ]]; then
    echo "🔑 Script needs root privileges, re-running with sudo..."
    exec sudo -E "$0" "$@"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
DEFAULT_MOUNT_POINT="/mnt/aidrive"
DEFAULT_CACHE_LOCATION="/tmp/aidrive_cache"
PID_FILE="/tmp/aidrive-mount.pid"
LOG_FILE="/tmp/aidrive-mount.log"

# Script variables
MOUNT_POINT=""
CACHE_LOCATION=""
ACTION="start"  # start, stop, status
DEBUG=false
TIMEOUT=30  # seconds to wait for mount

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Show usage information
show_usage() {
    cat << EOF
AI Drive FUSE Async Mount Script for E2B/Sandbox environments

Usage: $0 [ACTION] [OPTIONS] [MOUNT_POINT]

Actions:
  start               Start the AI Drive mount daemon (default)
  stop                Stop the AI Drive mount daemon
  status              Check if AI Drive is mounted
  restart             Restart the mount daemon

Arguments:
  MOUNT_POINT         Directory to mount AI Drive (default: $DEFAULT_MOUNT_POINT)

Options:
  --cache-location    Custom cache directory (default: $DEFAULT_CACHE_LOCATION)
  --debug             Enable debug output
  --timeout           Timeout in seconds to wait for mount (default: $TIMEOUT)
  -h, --help          Show this help message

Environment Variables (required for start):
  GENSPARK_TOKEN                Authentication token
  GENSPARK_BASE_URL            API base URL
  GENSPARK_AIDRIVE_API_PREFIX  API prefix (default: /api/aidrive)

Examples:
  $0 start                              # Start mount daemon
  $0 stop                               # Stop mount daemon
  $0 status                             # Check mount status
  $0 start /home/user/aidrive          # Mount to custom location
  $0 start --timeout 10                 # Start with 10 second timeout

EOF
}

# Parse command line arguments
parse_args() {
    # First argument might be action
    if [[ $# -gt 0 ]]; then
        case $1 in
            start|stop|status|restart)
                ACTION="$1"
                shift
                ;;
        esac
    fi
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            --debug)
                DEBUG=true
                shift
                ;;
            --cache-location)
                CACHE_LOCATION="$2"
                shift 2
                ;;
            --cache-location=*)
                CACHE_LOCATION="${1#*=}"
                shift
                ;;
            --timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            --timeout=*)
                TIMEOUT="${1#*=}"
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
            *)
                if [[ -z "$MOUNT_POINT" ]]; then
                    MOUNT_POINT="$1"
                else
                    log_error "Multiple mount points specified"
                    exit 1
                fi
                shift
                ;;
        esac
    done
    
    # Use defaults if not specified
    MOUNT_POINT="${MOUNT_POINT:-$DEFAULT_MOUNT_POINT}"
    CACHE_LOCATION="${CACHE_LOCATION:-$DEFAULT_CACHE_LOCATION}"
    
    # Convert to absolute paths
    MOUNT_POINT="$(realpath -m "$MOUNT_POINT")"
    CACHE_LOCATION="$(realpath -m "$CACHE_LOCATION")"
}

# Check if mount daemon is running
is_daemon_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        
        # If we couldn't track the PID but mount is active
        if [[ "$pid" == "unknown" ]]; then
            if is_mounted; then
                return 0  # Daemon is likely running
            else
                rm -f "$PID_FILE"
                return 1
            fi
        fi
        
        # Normal PID check
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        else
            # PID file exists but process is dead
            rm -f "$PID_FILE"
        fi
    fi
    return 1
}

# Check if filesystem is mounted
is_mounted() {
    mountpoint -q "$MOUNT_POINT" 2>/dev/null
}

# Start the mount daemon
start_daemon() {
    log_info "Starting AI Drive mount daemon..."
    
    # Check if already running
    if is_daemon_running; then
        local pid=$(cat "$PID_FILE")
        log_warning "Mount daemon already running (PID: $pid)"
        if is_mounted; then
            log_success "AI Drive is mounted at: $MOUNT_POINT"
        else
            log_warning "Daemon is running but filesystem is not mounted"
        fi
        return 0
    fi
    
    # Check environment
    if [[ -z "${GENSPARK_TOKEN:-}" ]]; then
        log_error "GENSPARK_TOKEN environment variable is required"
        return 1
    fi
    
    # Create mount point if needed
    if [[ ! -d "$MOUNT_POINT" ]]; then
        log_info "Creating mount point: $MOUNT_POINT"
        mkdir -p "$MOUNT_POINT"
    fi
    
    # Create cache directory
    mkdir -p "$CACHE_LOCATION"
    
    # Find mount_daemon.py
    local script_dir="$(dirname "${BASH_SOURCE[0]}")"
    local daemon_script="$script_dir/mount_daemon.py"
    
    if [[ ! -f "$daemon_script" ]]; then
        # Try relative to current directory
        daemon_script="./scripts/mount_daemon.py"
        if [[ ! -f "$daemon_script" ]]; then
            log_error "mount_daemon.py not found"
            return 1
        fi
    fi
    
    # Build daemon command array to handle paths with spaces
    local daemon_cmd_array=(
        "sudo" "-E" "python3" "$daemon_script"
        "$MOUNT_POINT"
        "--cache-location" "$CACHE_LOCATION"
    )
    
    if [[ "$DEBUG" == "true" ]]; then
        daemon_cmd_array+=("--debug")
    fi
    
    # Start daemon in background
    log_info "Starting mount daemon in background..."
    log_info "Mount point: $MOUNT_POINT"
    log_info "Cache location: $CACHE_LOCATION"
    log_info "Log file: $LOG_FILE"
    
    # Use nohup to detach from terminal, properly handling the command array
    nohup "${daemon_cmd_array[@]}" > "$LOG_FILE" 2>&1 &
    local daemon_pid=$!
    
    # Wait for python process to start and find its PID
    local max_attempts=30
    local attempt=0
    local python_pid=""
    
    # Escape mount point for use in regex
    local escaped_mount_point=$(printf '%s\n' "$MOUNT_POINT" | sed 's/[][\.*^$()+?{|}]/\\&/g')
    
    while [[ $attempt -lt $max_attempts ]]; do
        # Look for the python process with escaped mount point
        python_pid=$(pgrep -f "python3.*mount_daemon\\.py.*${escaped_mount_point}" | head -1)
        
        if [[ -n "$python_pid" ]]; then
            echo "$python_pid" > "$PID_FILE"
            log_info "Mount daemon started with PID: $python_pid"
            break
        fi
        
        # Don't check the wrapper process as it may exit while daemon continues
        # Just wait a bit longer for the actual Python process to appear
        
        ((attempt++))
        sleep 0.5
    done
    
    if [[ -z "$python_pid" ]]; then
        log_warning "Could not find python daemon process after $max_attempts attempts"
        # Don't use the wrapper PID as it may have already exited
        # We'll verify mount success below and use "unknown" as PID if needed
    else
        # Save the actual Python daemon PID
        echo "$python_pid" > "$PID_FILE"
    fi
    
    # Wait for mount to complete
    log_info "Waiting for mount to complete (timeout: ${TIMEOUT}s)..."
    local waited=0
    while [[ $waited -lt $TIMEOUT ]]; do
        if is_mounted; then
            log_success "AI Drive mounted successfully at: $MOUNT_POINT"
            
            # If we haven't saved a PID yet, save "unknown" to indicate mount is active
            if [[ ! -f "$PID_FILE" ]]; then
                echo "unknown" > "$PID_FILE"
                log_info "Mount successful but daemon PID unknown - tracking by mount status"
            fi
            
            # Show initial directory listing
            if command -v ls >/dev/null 2>&1; then
                log_info "Mount contents:"
                sudo ls -la "$MOUNT_POINT/" 2>/dev/null || true
            fi
            
            return 0
        fi
        
        # Don't check wrapper process - it may exit while daemon continues
        # Just keep waiting for mount to succeed
        
        sleep 1
        ((waited++))
        
        # Show progress
        if [[ $((waited % 5)) -eq 0 ]]; then
            log_info "Still waiting... (${waited}s elapsed)"
        fi
    done
    
    # Timeout reached
    log_error "Mount timeout after ${TIMEOUT}s"
    log_info "Check if mount is still in progress..."
    
    # Check one more time
    if is_mounted; then
        log_success "Mount completed just after timeout"
        return 0
    fi
    
    # Show log output
    if [[ -f "$LOG_FILE" ]]; then
        log_info "Mount log (last 20 lines):"
        tail -20 "$LOG_FILE"
    fi
    
    return 1
}

# Stop the mount daemon
stop_daemon() {
    log_info "Stopping AI Drive mount daemon..."
    
    # First try to unmount
    if is_mounted; then
        log_info "Unmounting $MOUNT_POINT..."
        if fusermount -u "$MOUNT_POINT" 2>/dev/null || umount "$MOUNT_POINT" 2>/dev/null; then
            log_success "Filesystem unmounted"
        else
            log_warning "Failed to unmount filesystem"
        fi
    fi
    
    # Then stop daemon
    if is_daemon_running; then
        local pid=$(cat "$PID_FILE")
        log_info "Stopping daemon (PID: $pid)..."
        
        # Handle unknown PID case
        if [[ "$pid" == "unknown" ]]; then
            log_warning "Daemon PID unknown, trying to find process..."
            # Try to find the actual daemon process
            local escaped_mount_point=$(printf '%s\n' "$MOUNT_POINT" | sed 's/[][\.*^$()+?{|}]/\\&/g')
            pid=$(pgrep -f "python3.*mount_daemon\\.py.*${escaped_mount_point}" | head -1)
            
            if [[ -z "$pid" ]]; then
                log_warning "Could not find daemon process"
                rm -f "$PID_FILE"
                return 0
            fi
            log_info "Found daemon process: $pid"
        fi
        
        # Try graceful shutdown first
        if kill "$pid" 2>/dev/null; then
            # Wait up to 5 seconds for graceful shutdown
            local count=0
            while [[ $count -lt 5 ]] && kill -0 "$pid" 2>/dev/null; do
                sleep 1
                ((count++))
            done
            
            # Force kill if still running
            if kill -0 "$pid" 2>/dev/null; then
                log_warning "Daemon did not stop gracefully, forcing..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        
        rm -f "$PID_FILE"
        log_success "Mount daemon stopped"
    else
        log_info "Mount daemon is not running"
    fi
    
    # Final cleanup
    if is_mounted; then
        log_warning "Filesystem is still mounted after daemon stop"
    fi
}

# Check daemon status
check_status() {
    local running=false
    local mounted=false
    local pid=""
    
    if is_daemon_running; then
        running=true
        pid=$(cat "$PID_FILE")
    fi
    
    if is_mounted; then
        mounted=true
    fi
    
    # Print status
    if [[ "$running" == "true" ]] && [[ "$mounted" == "true" ]]; then
        log_success "AI Drive is running and mounted"
        log_info "Daemon PID: $pid"
        log_info "Mount point: $MOUNT_POINT"
    elif [[ "$running" == "true" ]] && [[ "$mounted" == "false" ]]; then
        log_warning "Daemon is running but filesystem is not mounted"
        log_info "Daemon PID: $pid"
    elif [[ "$running" == "false" ]] && [[ "$mounted" == "true" ]]; then
        log_warning "Filesystem is mounted but daemon is not tracked"
        log_info "Mount point: $MOUNT_POINT"
    else
        log_info "AI Drive is not mounted"
    fi
    
    # Show mount info if available
    if [[ "$mounted" == "true" ]]; then
        mount | grep "$MOUNT_POINT" || true
    fi
    
    # Return appropriate exit code
    if [[ "$running" == "true" ]] && [[ "$mounted" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# Main function
main() {
    # Parse arguments
    parse_args "$@"
    
    case "$ACTION" in
        start)
            start_daemon
            ;;
        stop)
            stop_daemon
            ;;
        status)
            check_status
            ;;
        restart)
            stop_daemon
            sleep 2
            start_daemon
            ;;
        *)
            log_error "Unknown action: $ACTION"
            show_usage
            exit 1
            ;;
    esac
}

# Handle script interruption
handle_interrupt() {
    log_warning "Script interrupted"
    exit 1
}

trap handle_interrupt INT TERM

# Run main function
main "$@"