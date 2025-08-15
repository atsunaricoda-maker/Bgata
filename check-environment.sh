#!/bin/bash
set -euo pipefail

# AI Drive FUSE Environment Check Script
# This script checks if the environment is properly configured for AI Drive FUSE

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Check counts
CHECKS_TOTAL=0
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# Increment check counters
check_passed() {
    ((CHECKS_TOTAL++))
    ((CHECKS_PASSED++))
    log_success "$1"
}

check_failed() {
    ((CHECKS_TOTAL++))
    ((CHECKS_FAILED++))
    log_error "$1"
}

check_warning() {
    ((CHECKS_TOTAL++))
    ((CHECKS_WARNING++))
    log_warning "$1"
}

# Check system prerequisites
check_system() {
    log_info "Checking system prerequisites..."
    
    # Check Python
    if command -v python3 &> /dev/null; then
        local version=$(python3 --version 2>&1 | cut -d' ' -f2)
        check_passed "Python 3 available: $version"
    else
        check_failed "Python 3 not found"
    fi
    
    # Check pip
    if command -v pip3 &> /dev/null; then
        check_passed "pip3 available"
    else
        check_failed "pip3 not found"
    fi
    
    # Check FUSE
    if [[ -e /dev/fuse ]]; then
        check_passed "FUSE device available: /dev/fuse"
    else
        check_failed "FUSE device not found: /dev/fuse"
        log_info "Install FUSE with: sudo apt-get install fuse3"
    fi
    
    # Check FUSE filesystem support
    if grep -q fuse /proc/filesystems 2>/dev/null; then
        check_passed "FUSE filesystem support available"
    else
        check_failed "FUSE filesystem support not found"
    fi
    
    # Check user groups
    if groups | grep -q fuse; then
        check_passed "User is in 'fuse' group"
    else
        check_warning "User not in 'fuse' group (may need sudo for mounting)"
        log_info "Add to group with: sudo usermod -a -G fuse \$USER"
    fi
}

# Check Python packages
check_python_packages() {
    log_info "Checking Python packages..."
    
    local packages=("fusepy" "psutil")
    
    for package in "${packages[@]}"; do
        if python3 -c "import $package" 2>/dev/null; then
            local version=$(python3 -c "import $package; print(getattr($package, '__version__', 'unknown'))" 2>/dev/null || echo "unknown")
            check_passed "Python package '$package' available: $version"
        else
            check_failed "Python package '$package' not found"
            log_info "Install with: pip3 install $package"
        fi
    done
    
    # Check AI Drive SDK
    if python3 -c "import genspark_aidrive_sdk" 2>/dev/null; then
        local version=$(python3 -c "import genspark_aidrive_sdk; print(genspark_aidrive_sdk.__version__)" 2>/dev/null || echo "unknown")
        check_passed "GenSpark AI Drive SDK available: $version"
    else
        check_warning "GenSpark AI Drive SDK not found (should be pre-installed in VM)"
    fi
}

# Check environment variables
check_environment_variables() {
    log_info "Checking environment variables..."
    
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
        if [[ -n "${!var:-}" ]]; then
            local value_preview="${!var:0:8}..."
            check_passed "Required variable '$var' is set: $value_preview"
        else
            check_failed "Required variable '$var' is not set"
        fi
    done
    
    # Check optional variables
    for var in "${optional_vars[@]}"; do
        if [[ -n "${!var:-}" ]]; then
            check_passed "Optional variable '$var' is set: ${!var}"
        else
            log_info "Optional variable '$var' is not set"
        fi
    done
}

# Check AI Drive connectivity
check_aidrive_connectivity() {
    log_info "Checking AI Drive connectivity..."
    
    # Only check if we have the required environment
    if [[ -z "${GENSPARK_TOKEN:-}" ]]; then
        check_warning "Cannot test AI Drive connectivity - GENSPARK_TOKEN not set"
        return
    fi
    
    # Try to check authentication with aidrive command if available
    if command -v aidrive &> /dev/null; then
        if aidrive check-auth --quiet 2>/dev/null; then
            check_passed "AI Drive authentication successful"
            
            # Try to list root directory
            if aidrive list / --quiet 2>/dev/null; then
                check_passed "AI Drive file operations working"
            else
                check_warning "AI Drive authentication works but file operations failed"
            fi
        else
            check_failed "AI Drive authentication failed"
        fi
    else
        check_warning "Cannot test AI Drive connectivity - aidrive command not available"
    fi
}

# Check AI Drive FUSE installation
check_aidrive_fuse() {
    log_info "Checking AI Drive FUSE installation..."
    
    # Check if aidrive-mount command is available
    if command -v aidrive-mount &> /dev/null; then
        local version=$(aidrive-mount --version 2>&1 | head -1 || echo "unknown version")
        check_passed "aidrive-mount command available: $version"
        
        # Check dependencies
        if aidrive-mount --check-deps &> /dev/null; then
            check_passed "All AI Drive FUSE dependencies satisfied"
        else
            check_warning "Some AI Drive FUSE dependencies missing"
            aidrive-mount --check-deps 2>&1 | while read -r line; do
                log_info "  $line"
            done
        fi
    else
        check_failed "aidrive-mount command not found"
        log_info "Install with: ./install-aidrive-fuse.sh"
    fi
    
    # Check configuration file
    local config_files=(
        "/etc/aidrive-mount.conf"
        "$HOME/.config/aidrive-mount.conf"
        "$HOME/.aidrive-mount.conf"
        "./aidrive-mount.conf"
    )
    
    local config_found=false
    for config_file in "${config_files[@]}"; do
        if [[ -f "$config_file" ]]; then
            check_passed "Configuration file found: $config_file"
            config_found=true
            break
        fi
    done
    
    if [[ $config_found == false ]]; then
        check_warning "No configuration file found (will use defaults)"
    fi
}

# Check available mount points
check_mount_points() {
    log_info "Checking potential mount points..."
    
    local mount_points=(
        "/mnt/aidrive"
        "/tmp/aidrive"
        "$HOME/aidrive"
    )
    
    for mount_point in "${mount_points[@]}"; do
        if [[ -e "$mount_point" ]]; then
            if [[ -d "$mount_point" ]]; then
                if mountpoint -q "$mount_point" 2>/dev/null; then
                    check_warning "Mount point '$mount_point' is already mounted"
                elif [[ -z "$(ls -A "$mount_point" 2>/dev/null)" ]]; then
                    check_passed "Mount point '$mount_point' available (empty directory)"
                else
                    check_warning "Mount point '$mount_point' exists but not empty"
                fi
            else
                check_warning "Mount point '$mount_point' exists but is not a directory"
            fi
        else
            log_info "Mount point '$mount_point' does not exist (can be created)"
        fi
    done
}

# Show summary
show_summary() {
    echo ""
    log_info "Environment Check Summary"
    echo "================================"
    echo "Total checks: $CHECKS_TOTAL"
    echo -e "Passed: ${GREEN}$CHECKS_PASSED${NC}"
    echo -e "Warnings: ${YELLOW}$CHECKS_WARNING${NC}"
    echo -e "Failed: ${RED}$CHECKS_FAILED${NC}"
    echo ""
    
    if [[ $CHECKS_FAILED -eq 0 ]]; then
        if [[ $CHECKS_WARNING -eq 0 ]]; then
            log_success "Environment is fully ready for AI Drive FUSE!"
        else
            log_warning "Environment is mostly ready with some warnings"
        fi
        
        echo ""
        log_info "Ready to mount AI Drive:"
        log_info "  ./mount-aidrive.sh /mnt/aidrive"
        
    else
        log_error "Environment has issues that need to be resolved"
        
        echo ""
        log_info "To fix issues:"
        log_info "  1. Install missing system packages"
        log_info "  2. Run: ./install-aidrive-fuse.sh"
        log_info "  3. Check environment variables are set by sandbox"
        log_info "  4. Re-run this check script"
    fi
    
    echo ""
}

# Main function
main() {
    echo "AI Drive FUSE Environment Check"
    echo "==============================="
    echo ""
    
    check_system
    echo ""
    
    check_python_packages
    echo ""
    
    check_environment_variables
    echo ""
    
    check_aidrive_connectivity
    echo ""
    
    check_aidrive_fuse
    echo ""
    
    check_mount_points
    echo ""
    
    show_summary
    
    # Exit with appropriate code
    if [[ $CHECKS_FAILED -gt 0 ]]; then
        exit 1
    elif [[ $CHECKS_WARNING -gt 0 ]]; then
        exit 2
    else
        exit 0
    fi
}

# Run main function
main "$@"