#!/bin/bash
set -euo pipefail

# AI Drive FUSE Mount Script
# This script mounts AI Drive using the Python FUSE driver directly

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

# Script variables
MOUNT_POINT=""
CACHE_LOCATION=""
FORCE_MOUNT=false
FOREGROUND=false
DEBUG=false
DRY_RUN=false

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
AI Drive FUSE Mount Script

Usage: $0 [OPTIONS] [MOUNT_POINT]

Arguments:
  MOUNT_POINT         Directory to mount AI Drive (default: $DEFAULT_MOUNT_POINT)

Options:
  -f, --force         Force mount even if directory is not empty
  --foreground        Run in foreground mode (default is background)
  --debug             Enable debug output
  --cache-location    Custom cache directory (default: $DEFAULT_CACHE_LOCATION)
  --dry-run           Show what would be done without actually mounting
  -h, --help          Show this help message

Environment Variables (required):
  GENSPARK_TOKEN                Authentication token
  GENSPARK_BASE_URL            API base URL (optional)
  GENSPARK_AIDRIVE_API_PREFIX  API prefix (optional)
  GENSPARK_ROUTE_IDENTIFIER    Route identifier (optional)
  GENSPARK_ENVIRONMENT_ID      Environment ID (optional)

Examples:
  $0                                    # Mount to $DEFAULT_MOUNT_POINT (background mode)
  $0 /home/user/aidrive                # Mount to custom location (background mode)
  $0 --foreground /mnt/aidrive         # Run in foreground mode
  $0 --debug /tmp/aidrive              # Debug mode (background)
  $0 --cache-location /tmp/cache /mnt/ai # Custom cache location

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
                FORCE_MOUNT=true
                shift
                ;;
            --foreground)
                FOREGROUND=true
                shift
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
            --dry-run)
                DRY_RUN=true
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
    
    # Use default cache location if not specified
    if [[ -z "$CACHE_LOCATION" ]]; then
        CACHE_LOCATION="$DEFAULT_CACHE_LOCATION"
    fi
    
    # Convert to absolute paths
    MOUNT_POINT="$(realpath -m "$MOUNT_POINT")"
    CACHE_LOCATION="$(realpath -m "$CACHE_LOCATION")"
}

# Check required environment variables
check_environment() {
    log_info "Checking environment variables..."
    
    local missing_vars=()
    local found_vars=()
    
    # Required variables
    local required_vars=(
        "GENSPARK_TOKEN"
    )
    
    # Optional variables
    local optional_vars=(
        "GENSPARK_BASE_URL"
        "GENSPARK_AIDRIVE_API_PREFIX"  
        "GENSPARK_ROUTE_IDENTIFIER"
        "GENSPARK_ENVIRONMENT_ID"
    )
    
    # Check required variables
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("$var")
        else
            found_vars+=("$var")
        fi
    done
    
    # Check optional variables
    for var in "${optional_vars[@]}"; do
        if [[ -n "${!var:-}" ]]; then
            found_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log_error "Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            log_error "  - $var"
        done
        log_info "These variables should be automatically set in the GenSpark sandbox"
        return 1
    fi
    
    log_success "Found ${#found_vars[@]} environment variables"
    
    if [[ $DEBUG == true ]]; then
        log_info "Environment variables found:"
        for var in "${found_vars[@]}"; do
            if [[ "$var" == "GENSPARK_TOKEN" ]]; then
                local token_preview="${!var:0:8}..."
                log_info "  - $var: $token_preview"
            else
                log_info "  - $var: ${!var}"
            fi
        done
    fi
    
    return 0
}

# Check and setup FUSE system requirements
check_fuse_device() {
    log_info "Checking FUSE system requirements..."
    
    # Check if FUSE kernel module is loaded (if lsmod is available)
    if command -v lsmod >/dev/null 2>&1; then
        if ! lsmod | grep -q "^fuse "; then
            log_warning "FUSE kernel module may not be loaded"
            log_info "Attempting to load FUSE module..."
            if ! modprobe fuse 2>/dev/null; then
                log_warning "Could not load FUSE module automatically"
            fi
        fi
    else
        log_info "lsmod not available - skipping kernel module check"
    fi
    
    # Check FUSE device
    if [[ ! -e "/dev/fuse" ]]; then
        log_error "FUSE device not found: /dev/fuse"
        log_info "FUSE may not be available in this environment"
        log_info "Please ensure FUSE is properly installed:"
        log_info "  sudo apt-get install fuse libfuse2 libfuse-dev"
        return 1
    fi
    
    # Set FUSE device permissions
    log_info "Setting FUSE device permissions..."
    if ! chmod 666 /dev/fuse 2>/dev/null; then
        log_warning "Failed to set /dev/fuse permissions (may not be needed)"
    else
        log_success "FUSE device permissions set successfully"
    fi
    
    # Check if fusepy is available
    if ! python3 -c "import fuse" 2>/dev/null; then
        log_error "fusepy Python package not available"
        log_info "Please install fusepy: pip3 install fusepy"
        return 1
    fi
    
    log_success "FUSE system requirements satisfied"
    return 0
}

# Check if Python packages are available
check_python_packages() {
    log_info "Checking AI Drive FUSE Python packages..."
    
    # Check aidrive_fuse package
    if ! python3 -c "import aidrive_fuse" 2>/dev/null; then
        log_error "aidrive_fuse Python package not found"
        log_info "Please run the installation script first:"
        log_info "  ./quick-install.sh"
        return 1
    fi
    
    # Check genspark_aidrive_sdk package
    if ! python3 -c "import genspark_aidrive_sdk" 2>/dev/null; then
        log_error "genspark_aidrive_sdk Python package not found"
        log_info "Please run the installation script first:"
        log_info "  ./quick-install.sh"
        return 1
    fi
    
    
    log_success "All required Python packages are available"
    return 0
}

# Validate mount point
validate_mount_point() {
    log_info "Validating mount point: $MOUNT_POINT"
    
    # Check if mount point already exists
    if [[ -e "$MOUNT_POINT" ]]; then
        if [[ ! -d "$MOUNT_POINT" ]]; then
            log_error "Mount point exists but is not a directory: $MOUNT_POINT"
            return 1
        fi
        
        # Check if already mounted
        if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
            log_error "Something is already mounted at: $MOUNT_POINT"
            log_info "Unmount first with: umount $MOUNT_POINT"
            return 1
        fi
        
        # Check if directory is empty
        if [[ $FORCE_MOUNT == false ]] && [[ -n "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]]; then
            log_error "Mount point directory is not empty: $MOUNT_POINT"
            log_info "Use --force to mount anyway, or choose an empty directory"
            return 1
        fi
    else
        # Create mount point directory
        log_info "Creating mount point directory: $MOUNT_POINT"
        if [[ $DRY_RUN == false ]]; then
            mkdir -p "$MOUNT_POINT"
        fi
    fi
    
    # Check permissions
    if [[ $DRY_RUN == false ]] && [[ ! -r "$MOUNT_POINT" || ! -w "$MOUNT_POINT" ]]; then
        log_error "Insufficient permissions for mount point: $MOUNT_POINT"
        return 1
    fi
    
    log_success "Mount point validation passed"
    return 0
}


# Check if unmount is needed
cleanup_on_error() {
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        log_warning "Cleaning up failed mount..."
        umount "$MOUNT_POINT" 2>/dev/null || true
    fi
}

# Mount AI Drive
mount_aidrive() {
    log_info "Mounting AI Drive..."
    log_info "Mount point: $MOUNT_POINT"
    log_info "Cache location: $CACHE_LOCATION"
    
    if [[ $DRY_RUN == true ]]; then
        log_info "DRY RUN - would mount AI Drive using mount_daemon.py"
        log_info "  Mount point: $MOUNT_POINT"
        log_info "  Cache location: $CACHE_LOCATION"
        local dry_run_cmd="sudo -E python3 scripts/mount_daemon.py \"$MOUNT_POINT\" --cache-location \"$CACHE_LOCATION\""
        if [[ "$FOREGROUND" == "true" ]]; then
            dry_run_cmd+=" --foreground"
        fi
        if [[ "$DEBUG" == "true" ]]; then
            dry_run_cmd+=" --debug"
        fi
        log_info "  Command: $dry_run_cmd"
        return 0
    fi
    
    # Create cache directory
    mkdir -p "$CACHE_LOCATION"
    
    # Check if mount_daemon.py exists
    local script_dir="$(dirname "${BASH_SOURCE[0]}")"
    local daemon_script="$script_dir/mount_daemon.py"
    
    if [[ ! -f "$daemon_script" ]]; then
        log_error "mount_daemon.py not found at: $daemon_script"
        return 1
    fi
    
    # Set up error cleanup
    trap cleanup_on_error ERR
    
    # Execute mount command using the proven mount_daemon.py
    log_info "Starting AI Drive FUSE daemon..."
    log_info "Using script: $daemon_script"
    log_info "Mount point: $MOUNT_POINT"
    log_info "Cache location: $CACHE_LOCATION"
    
    # Build daemon command with arguments
    local daemon_args=()
    daemon_args+=("$MOUNT_POINT")
    daemon_args+=("--cache-location" "$CACHE_LOCATION")
    
    if [[ "$DEBUG" == "true" ]]; then
        daemon_args+=("--debug")
    fi
    
    # Always run in background mode by default
    # Only use foreground mode if explicitly requested with --foreground
    if [[ "$FOREGROUND" != "true" ]]; then
        # Run in background mode - start daemon and return immediately
        log_info "Starting mount daemon in background mode..."
        
        # Create log file
        local log_file="/tmp/aidrive-mount-$(date +%Y%m%d-%H%M%S).log"
        
        # Start daemon in background
        nohup sudo -E python3 "$daemon_script" "${daemon_args[@]}" > "$log_file" 2>&1 &
        local daemon_pid=$!
        
        log_success "Mount daemon started in background (PID: $daemon_pid)"
        log_info "Log file: $log_file"
        
        # Check if daemon process started successfully
        if ! kill -0 "$daemon_pid" 2>/dev/null; then
            log_error "Failed to start mount daemon process"
            return 1
        fi
        
        # In background mode, we don't wait for verification
        # The mount will complete asynchronously
        log_info "Mount daemon is initializing in background..."
        log_info "To check mount status: mountpoint -q $MOUNT_POINT"
        log_info "To check daemon status: ps aux | grep mount_daemon"
        log_info "To view logs: tail -f $log_file"
        
        # Disable error cleanup trap before returning success
        trap - ERR
        
        # Return success immediately in background mode
        return 0
    else
        # Foreground mode - run daemon in foreground
        log_info "Starting mount daemon in foreground mode..."
        log_info "Press Ctrl+C to stop the mount daemon"
        
        # Run daemon in foreground - it will block until interrupted
        sudo -E python3 "$daemon_script" "${daemon_args[@]}"
        local mount_exit_code=$?
        
        # Daemon has exited (either normally or via interrupt)
        if [[ $mount_exit_code -eq 0 ]]; then
            log_info "Mount daemon exited normally"
        else
            log_error "Mount daemon exited with code: $mount_exit_code"
        fi
        
        # Disable error cleanup trap before returning
        trap - ERR
        
        return $mount_exit_code
    fi
}

# Show post-mount information
show_post_mount_info() {
    if [[ $DRY_RUN == true ]]; then
        return 0
    fi
    
    cat << EOF

🎉 AI Drive Successfully Mounted!

Mount Point: $MOUNT_POINT
Cache Location: $CACHE_LOCATION
Access your AI Drive files using standard commands:

  ls $MOUNT_POINT/
  echo "Hello World" | sudo tee $MOUNT_POINT/test.txt
  sudo cp localfile.txt $MOUNT_POINT/
  sudo mkdir $MOUNT_POINT/newfolder/

To unmount:
  sudo umount $MOUNT_POINT
  # or
  sudo fusermount -u $MOUNT_POINT

To check mount status:
  mount | grep $MOUNT_POINT

For troubleshooting:
  # Check if mounted
  mountpoint $MOUNT_POINT
  
  # Check FUSE processes
  ps aux | grep python3 | grep aidrive

EOF

    # Show current directory contents if mounted
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        log_info "Current contents of AI Drive:"
        sudo ls -la "$MOUNT_POINT/" 2>/dev/null || log_warning "Unable to list contents"
    fi
}

# Main function
main() {
    log_info "AI Drive FUSE Mount Script"
    
    # Parse arguments
    parse_args "$@"
    
    # Run checks (order matters: system deps first, then Python packages)
    check_environment || exit 1
    check_fuse_device || exit 1
    check_python_packages || exit 1
    validate_mount_point || exit 1
    
    # Mount AI Drive
    if mount_aidrive; then
        show_post_mount_info
        
        if [[ $FOREGROUND == false ]]; then
            log_success "AI Drive is now available at: $MOUNT_POINT"
        fi
    else
        log_error "Failed to mount AI Drive"
        exit 1
    fi
}

# Handle script interruption
handle_interrupt() {
    log_warning "Mount interrupted"
    cleanup_on_error
    exit 1
}

trap handle_interrupt INT TERM

# Run main function
main "$@"