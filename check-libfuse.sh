#!/bin/bash
set -euo pipefail

# LibFUSE Installation Check Script
# This script checks if libfuse is installed and installs it if needed for sandbox deployment

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

# Check if libfuse is available
check_libfuse() {
    log_info "Checking for libfuse..."
    
    # Check for FUSE3 first (preferred)
    if command -v fusermount3 >/dev/null 2>&1; then
        log_success "FUSE3 is available (fusermount3 found)"
        return 0
    fi
    
    # Check for older FUSE
    if command -v fusermount >/dev/null 2>&1; then
        log_success "FUSE is available (fusermount found)"
        return 0
    fi
    
    # Check for FUSE kernel module
    if [[ -e /dev/fuse ]]; then
        log_info "FUSE device exists (/dev/fuse)"
        return 0
    fi
    
    # Check for FUSE library
    if ldconfig -p | grep -q libfuse; then
        log_info "FUSE library found via ldconfig"
        return 0
    fi
    
    return 1
}

# Install libfuse based on the distribution
install_libfuse() {
    log_info "Installing libfuse..."
    
    # Detect the Linux distribution
    if command -v apt-get >/dev/null 2>&1; then
        # Debian/Ubuntu
        log_info "Detected Debian/Ubuntu system"
        sudo apt-get update
        sudo apt-get install -y fuse3 libfuse3-dev || sudo apt-get install -y fuse libfuse-dev
        
    elif command -v yum >/dev/null 2>&1; then
        # RHEL/CentOS/Fedora
        log_info "Detected RHEL/CentOS/Fedora system"
        sudo yum install -y fuse3 fuse3-devel || sudo yum install -y fuse fuse-devel
        
    elif command -v dnf >/dev/null 2>&1; then
        # Modern Fedora
        log_info "Detected Fedora system (dnf)"
        sudo dnf install -y fuse3 fuse3-devel || sudo dnf install -y fuse fuse-devel
        
    elif command -v pacman >/dev/null 2>&1; then
        # Arch Linux
        log_info "Detected Arch Linux system"
        sudo pacman -S --noconfirm fuse3 || sudo pacman -S --noconfirm fuse2
        
    elif command -v zypper >/dev/null 2>&1; then
        # openSUSE
        log_info "Detected openSUSE system"
        sudo zypper install -y fuse3 fuse3-devel || sudo zypper install -y fuse fuse-devel
        
    elif command -v apk >/dev/null 2>&1; then
        # Alpine Linux
        log_info "Detected Alpine Linux system"
        sudo apk add fuse3 fuse3-dev || sudo apk add fuse fuse-dev
        
    else
        log_error "Unknown Linux distribution. Please install libfuse manually."
        echo "Required packages:"
        echo "  - fuse3 or fuse"
        echo "  - fuse3-dev/fuse3-devel or fuse-dev/fuse-devel"
        return 1
    fi
    
    log_success "libfuse installation completed"
}

# Check if user can use FUSE
check_fuse_permissions() {
    log_info "Checking FUSE permissions..."
    
    # Check if user is in fuse group
    if groups | grep -q fuse; then
        log_success "User is in 'fuse' group"
        return 0
    fi
    
    # Check if user_allow_other is enabled in fuse.conf
    if [[ -f /etc/fuse.conf ]] && grep -q "^user_allow_other" /etc/fuse.conf; then
        log_info "user_allow_other is enabled in /etc/fuse.conf"
    else
        log_warning "user_allow_other is not enabled in /etc/fuse.conf"
        log_info "You may need to enable it for some mounting options to work"
    fi
    
    # Check if we can access /dev/fuse
    if [[ -r /dev/fuse && -w /dev/fuse ]]; then
        log_success "User can access /dev/fuse"
        return 0
    else
        log_warning "User may not have proper access to /dev/fuse"
        log_info "This is normal in some sandbox environments"
        return 0
    fi
}

# Test FUSE functionality
test_fuse() {
    log_info "Testing FUSE functionality..."
    
    # Create a temporary test directory
    local test_dir=$(mktemp -d)
    local mount_point="$test_dir/mount"
    mkdir -p "$mount_point"
    
    # Try to mount a simple FUSE filesystem (if available)
    if command -v python3 >/dev/null 2>&1; then
        # Try to test with a simple Python FUSE test
        cat > "$test_dir/test_fuse.py" << 'EOF'
import os
import sys
import tempfile
try:
    import fuse
    print("FUSE Python bindings available")
    sys.exit(0)
except ImportError:
    print("FUSE Python bindings not available")
    sys.exit(1)
EOF
        
        if python3 "$test_dir/test_fuse.py" >/dev/null 2>&1; then
            log_success "FUSE Python bindings are available"
        else
            log_warning "FUSE Python bindings not available (will be installed with aidrive-fuse)"
        fi
    fi
    
    # Clean up
    rm -rf "$test_dir"
    
    log_success "FUSE functionality test completed"
}

# Main function
main() {
    echo "🔍 LibFUSE Installation Check for AI Drive FUSE"
    echo "==============================================="
    echo ""
    
    # Check if libfuse is already available
    if check_libfuse; then
        log_success "LibFUSE is already available"
    else
        log_warning "LibFUSE not found, attempting to install..."
        
        if ! install_libfuse; then
            log_error "Failed to install libfuse"
            exit 1
        fi
        
        # Verify installation
        if check_libfuse; then
            log_success "LibFUSE installation verified"
        else
            log_error "LibFUSE installation verification failed"
            exit 1
        fi
    fi
    
    echo ""
    
    # Check permissions
    check_fuse_permissions
    
    echo ""
    
    # Test functionality
    test_fuse
    
    echo ""
    log_success "LibFUSE check completed successfully!"
    echo ""
    echo "✅ Your system is ready for AI Drive FUSE installation"
    echo ""
    echo "Next steps:"
    echo "  1. Run: ./install-aidrive-fuse.sh"
    echo "  2. Mount: ./mount-aidrive.sh /mnt/aidrive"
}

# Show usage if requested
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat << EOF
LibFUSE Installation Check Script

This script checks if libfuse is installed and working properly,
and installs it if needed for AI Drive FUSE to work in sandbox environments.

Usage: $0 [OPTIONS]

Options:
  --help, -h    Show this help message

Examples:
  $0            Check and install libfuse if needed

This script is designed to be run in sandbox environments before
installing AI Drive FUSE to ensure all dependencies are available.
EOF
    exit 0
fi

# Run main function
main "$@"