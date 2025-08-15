#!/bin/bash
set -euo pipefail

# AI Drive FUSE Unmount Script
# This script safely unmounts AI Drive FUSE filesystems

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
DEFAULT_MOUNT_POINT="/mnt/aidrive"

# Script variables
MOUNT_POINT=""
FORCE_UNMOUNT=false
KILL_PROCESSES=false
CLEANUP_CACHE=false

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
AI Drive FUSE Unmount Script

Usage: $0 [OPTIONS] [MOUNT_POINT]

Arguments:
  MOUNT_POINT         Directory to unmount (default: $DEFAULT_MOUNT_POINT)

Options:
  -f, --force         Force unmount (lazy unmount)
  -k, --kill          Kill processes using the mount point
  -c, --cleanup       Clean up cache after unmount
  -h, --help          Show this help message

Examples:
  $0                           # Unmount $DEFAULT_MOUNT_POINT
  $0 /home/user/aidrive        # Unmount custom location
  $0 --force --cleanup /mnt/ai # Force unmount and cleanup cache

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -f|--force)
                FORCE_UNMOUNT=true
                shift
                ;;
            -k|--kill)
                KILL_PROCESSES=true
                shift
                ;;
            -c|--cleanup)
                CLEANUP_CACHE=true
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
    
    # Use default mount point if not specified
    if [[ -z "$MOUNT_POINT" ]]; then
        MOUNT_POINT="$DEFAULT_MOUNT_POINT"
    fi
    
    # Convert to absolute path
    MOUNT_POINT="$(realpath -m "$MOUNT_POINT")"
}

# Check if mount point is mounted
check_mounted() {
    if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        log_warning "$MOUNT_POINT is not mounted"
        return 1
    fi
    
    log_info "$MOUNT_POINT is currently mounted"
    return 0
}

# Show mount information
show_mount_info() {
    log_info "Mount point information:"
    
    # Show mount details
    if mount | grep -q "$MOUNT_POINT"; then
        mount | grep "$MOUNT_POINT" | while read -r line; do
            log_info "  $line"
        done
    fi
    
    # Show disk usage if possible
    if df -h "$MOUNT_POINT" 2>/dev/null | tail -1; then
        local usage=$(df -h "$MOUNT_POINT" 2>/dev/null | tail -1)
        log_info "  Usage: $usage"
    fi
}

# Find processes using the mount point
find_processes() {
    local processes=()
    
    # Use lsof to find processes
    if command -v lsof &> /dev/null; then
        local lsof_output
        if lsof_output=$(lsof +D "$MOUNT_POINT" 2>/dev/null); then
            while IFS= read -r line; do
                if [[ ! "$line" =~ ^COMMAND ]]; then
                    processes+=("$line")
                fi
            done <<< "$lsof_output"
        fi
    fi
    
    # Use fuser as backup
    if [[ ${#processes[@]} -eq 0 ]] && command -v fuser &> /dev/null; then
        local fuser_output
        if fuser_output=$(fuser -v "$MOUNT_POINT" 2>&1); then
            while IFS= read -r line; do
                if [[ ! "$line" =~ ^USER ]]; then
                    processes+=("$line")
                fi
            done <<< "$fuser_output"
        fi
    fi
    
    echo "${processes[@]}"
}

# Kill processes using the mount point
kill_processes() {
    log_info "Looking for processes using $MOUNT_POINT..."
    
    local processes
    processes=($(find_processes))
    
    if [[ ${#processes[@]} -eq 0 ]]; then
        log_info "No processes found using the mount point"
        return 0
    fi
    
    log_warning "Found ${#processes[@]} processes using the mount point:"
    for process in "${processes[@]}"; do
        log_warning "  $process"
    done
    
    if [[ $KILL_PROCESSES == true ]]; then
        log_info "Attempting to kill processes..."
        
        # Try graceful termination first
        if command -v fuser &> /dev/null; then
            fuser -k "$MOUNT_POINT" 2>/dev/null || true
            sleep 2
        fi
        
        # Check if processes are still running
        local remaining_processes
        remaining_processes=($(find_processes))
        
        if [[ ${#remaining_processes[@]} -gt 0 ]]; then
            log_warning "Some processes still running, using force kill..."
            if command -v fuser &> /dev/null; then
                fuser -9 -k "$MOUNT_POINT" 2>/dev/null || true
                sleep 1
            fi
        fi
        
        # Final check
        remaining_processes=($(find_processes))
        if [[ ${#remaining_processes[@]} -eq 0 ]]; then
            log_success "All processes terminated"
        else
            log_warning "Some processes may still be running"
        fi
    else
        log_info "Use --kill option to automatically terminate these processes"
        return 1
    fi
    
    return 0
}

# Unmount the filesystem
unmount_filesystem() {
    log_info "Unmounting $MOUNT_POINT..."
    
    # Try normal unmount first
    if umount "$MOUNT_POINT" 2>/dev/null; then
        log_success "Successfully unmounted $MOUNT_POINT"
        return 0
    fi
    
    log_warning "Normal unmount failed"
    
    # Check for processes
    if ! kill_processes && [[ $FORCE_UNMOUNT == false ]]; then
        log_error "Cannot unmount - processes are using the mount point"
        log_info "Use --kill to terminate processes or --force for lazy unmount"
        return 1
    fi
    
    # Try again after killing processes
    if umount "$MOUNT_POINT" 2>/dev/null; then
        log_success "Successfully unmounted $MOUNT_POINT after killing processes"
        return 0
    fi
    
    # Try force unmount if requested
    if [[ $FORCE_UNMOUNT == true ]]; then
        log_info "Attempting force unmount (lazy unmount)..."
        if umount -l "$MOUNT_POINT" 2>/dev/null; then
            log_success "Force unmount successful"
            log_warning "Mount point may still appear busy until all references are released"
            return 0
        else
            log_error "Force unmount failed"
            return 1
        fi
    else
        log_error "Unmount failed"
        log_info "Try --force option for lazy unmount"
        return 1
    fi
}

# Clean up cache
cleanup_cache() {
    if [[ $CLEANUP_CACHE == false ]]; then
        return 0
    fi
    
    log_info "Cleaning up AI Drive FUSE cache..."
    
    local cache_dirs=(
        "/tmp/aidrive-cache"
        "$HOME/.cache/aidrive-fuse"
        "/var/cache/aidrive-fuse"
    )
    
    local cleaned=false
    
    for cache_dir in "${cache_dirs[@]}"; do
        if [[ -d "$cache_dir" ]]; then
            log_info "Cleaning cache directory: $cache_dir"
            
            # Show cache size before cleanup
            local size_before
            if size_before=$(du -sh "$cache_dir" 2>/dev/null | cut -f1); then
                log_info "  Cache size: $size_before"
            fi
            
            # Remove cache files
            if rm -rf "$cache_dir"/* 2>/dev/null; then
                log_success "  Cache cleaned"
                cleaned=true
            else
                log_warning "  Failed to clean cache"
            fi
        fi
    done
    
    if [[ $cleaned == true ]]; then
        log_success "Cache cleanup completed"
    else
        log_info "No cache directories found to clean"
    fi
}

# Show post-unmount information
show_post_unmount_info() {
    cat << EOF

✅ AI Drive Unmounted Successfully!

Mount point $MOUNT_POINT is now available for other use.

To mount again:
  ./mount-aidrive.sh $MOUNT_POINT

To check status:
  aidrive-mount --status $MOUNT_POINT

EOF
}

# Main function
main() {
    log_info "AI Drive FUSE Unmount Script"
    
    # Parse arguments
    parse_args "$@"
    
    # Check if mounted
    if ! check_mounted; then
        log_info "Nothing to unmount"
        exit 0
    fi
    
    # Show mount information
    show_mount_info
    
    # Unmount filesystem
    if unmount_filesystem; then
        # Clean up cache if requested
        cleanup_cache
        
        # Verify unmount
        if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
            log_warning "Mount point still appears mounted (may be lazy unmount)"
        else
            log_success "Mount point successfully unmounted"
        fi
        
        show_post_unmount_info
    else
        log_error "Failed to unmount $MOUNT_POINT"
        exit 1
    fi
}

# Handle script interruption
handle_interrupt() {
    log_warning "Unmount interrupted"
    exit 1
}

trap handle_interrupt INT TERM

# Run main function
main "$@"