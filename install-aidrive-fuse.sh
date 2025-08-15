#!/bin/bash
set -euo pipefail

# AI Drive FUSE Installation Script
# This script installs the AI Drive FUSE mount tool in a VM environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

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

# Check if running as root for system installation
check_permissions() {
    if [[ $EUID -eq 0 ]]; then
        INSTALL_MODE="system"
        INSTALL_PREFIX="/usr/local"
        CONFIG_DIR="/etc"
        log_info "Installing system-wide as root"
    else
        INSTALL_MODE="user"
        INSTALL_PREFIX="$HOME/.local"
        CONFIG_DIR="$HOME/.config"
        log_info "Installing for current user"
    fi
}

# Check system requirements
check_requirements() {
    log_info "Checking system requirements..."
    
    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Python version: $PYTHON_VERSION"
    
    # Check if FUSE is available
    if [[ ! -e /dev/fuse ]]; then
        log_error "FUSE device /dev/fuse not found"
        log_info "Please install FUSE: sudo apt-get install fuse3"
        exit 1
    fi
    
    # Check if user is in fuse group (for non-root installs)
    if [[ $INSTALL_MODE == "user" ]] && ! groups | grep -q fuse; then
        log_warning "User is not in 'fuse' group"
        log_info "To add user to fuse group, run: sudo usermod -a -G fuse \$USER"
        log_info "Then log out and back in for changes to take effect"
    fi
    
    log_success "System requirements check passed"
}

# Install Python dependencies
install_python_deps() {
    log_info "Installing Python dependencies..."
    
    # Check if pip is available
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 is required but not installed"
        exit 1
    fi
    
    # Install required packages
    local pip_cmd="pip3 install"
    if [[ $INSTALL_MODE == "user" ]]; then
        pip_cmd="$pip_cmd --user"
    fi
    
    # Install from requirements if available
    if [[ -f "$PACKAGE_DIR/requirements.txt" ]]; then
        log_info "Installing from requirements.txt..."
        $pip_cmd -r "$PACKAGE_DIR/requirements.txt"
    else
        # Install basic requirements
        log_info "Installing basic requirements..."
        $pip_cmd fusepy psutil
    fi
    
    log_success "Python dependencies installed"
}

# Install AI Drive packages
install_aidrive_packages() {
    log_info "Installing AI Drive packages..."
    
    cd "$PACKAGE_DIR"
    
    local pip_cmd="pip3 install"
    if [[ $INSTALL_MODE == "user" ]]; then
        pip_cmd="$pip_cmd --user"
    fi
    
    # Install genspark-aidrive-sdk first (dependency)
    if ls genspark_aidrive_sdk*.whl &> /dev/null; then
        log_info "Installing genspark-aidrive-sdk from wheel..."
        local sdk_wheel=$(ls genspark_aidrive_sdk*.whl | head -1)
        $pip_cmd "$sdk_wheel"
        log_success "genspark-aidrive-sdk installed"
    else
        log_error "genspark-aidrive-sdk wheel not found"
        exit 1
    fi
    
    # Install aidrive-fuse package
    if ls aidrive_fuse*.whl &> /dev/null; then
        log_info "Installing aidrive-fuse from wheel..."
        local fuse_wheel=$(ls aidrive_fuse*.whl | head -1)
        $pip_cmd "$fuse_wheel"
        log_success "aidrive-fuse installed"
    elif [[ -f "aidrive-fuse/setup.py" ]]; then
        log_info "Installing aidrive-fuse from source..."
        cd aidrive-fuse
        $pip_cmd .
        log_success "aidrive-fuse installed from source"
    else
        log_error "No aidrive-fuse package found"
        exit 1
    fi
    
    log_success "All AI Drive packages installed"
}

# Install mount script and configuration
install_system_files() {
    log_info "Installing system files..."
    
    # Create directories
    mkdir -p "$INSTALL_PREFIX/bin"
    mkdir -p "$CONFIG_DIR"
    
    # Install mount script
    if [[ -f "$PACKAGE_DIR/aidrive-fuse/bin/aidrive-mount" ]]; then
        cp "$PACKAGE_DIR/aidrive-fuse/bin/aidrive-mount" "$INSTALL_PREFIX/bin/"
        chmod +x "$INSTALL_PREFIX/bin/aidrive-mount"
        log_info "Installed aidrive-mount to $INSTALL_PREFIX/bin/"
    fi
    
    # Install configuration file
    if [[ -f "$PACKAGE_DIR/aidrive-fuse/etc/aidrive-mount.conf" ]]; then
        if [[ ! -f "$CONFIG_DIR/aidrive-mount.conf" ]]; then
            cp "$PACKAGE_DIR/aidrive-fuse/etc/aidrive-mount.conf" "$CONFIG_DIR/"
            log_info "Installed configuration to $CONFIG_DIR/aidrive-mount.conf"
        else
            log_warning "Configuration file already exists at $CONFIG_DIR/aidrive-mount.conf"
        fi
    fi
    
    # Install systemd service (system-wide only)
    if [[ $INSTALL_MODE == "system" ]] && [[ -f "$PACKAGE_DIR/aidrive-fuse/systemd/aidrive-mount@.service" ]]; then
        cp "$PACKAGE_DIR/aidrive-fuse/systemd/aidrive-mount@.service" /lib/systemd/system/
        systemctl daemon-reload
        log_info "Installed systemd service"
    fi
    
    log_success "System files installed"
}

# Verify installation
verify_installation() {
    log_info "Verifying installation..."
    
    # Check if command is available
    if command -v aidrive-mount &> /dev/null; then
        local version=$(aidrive-mount --version 2>&1 | head -1 || echo "Unknown version")
        log_success "aidrive-mount command available: $version"
    else
        log_error "aidrive-mount command not found in PATH"
        log_info "You may need to add $INSTALL_PREFIX/bin to your PATH"
        if [[ $INSTALL_MODE == "user" ]]; then
            log_info "Add this to your ~/.bashrc or ~/.profile:"
            log_info "export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        return 1
    fi
    
    # Check dependencies
    if aidrive-mount --check-deps &> /dev/null; then
        log_success "All dependencies are available"
    else
        log_warning "Some dependencies may be missing"
        aidrive-mount --check-deps || true
    fi
    
    log_success "Installation verification completed"
}

# Check environment variables
check_env_vars() {
    log_info "Checking environment variables..."
    
    local missing_vars=()
    
    # Required environment variables for AI Drive SDK
    local required_vars=(
        "GENSPARK_TOKEN"
    )
    
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
            log_success "$var is set"
        fi
    done
    
    # Check optional variables
    for var in "${optional_vars[@]}"; do
        if [[ -n "${!var:-}" ]]; then
            log_info "$var is set"
        else
            log_info "$var is not set (optional)"
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log_warning "Missing required environment variables: ${missing_vars[*]}"
        log_info "These variables should be set by the sandbox environment"
        log_info "AI Drive mounting will not work without them"
        return 1
    else
        log_success "All required environment variables are set"
        return 0
    fi
}

# Main installation function
main() {
    log_info "Starting AI Drive FUSE installation..."
    
    # Change to script directory
    cd "$SCRIPT_DIR"
    
    # Run installation steps
    check_permissions
    check_requirements
    install_python_deps
    install_aidrive_packages
    install_system_files
    verify_installation
    
    # Check environment (don't fail installation if missing)
    if ! check_env_vars; then
        log_warning "Environment variables check failed, but installation completed"
    fi
    
    log_success "AI Drive FUSE installation completed successfully!"
    
    # Print usage information
    cat << EOF

🚀 Installation Complete!

To mount AI Drive:
  ./mount-aidrive.sh /mnt/aidrive

Or manually:
  mkdir -p /mnt/aidrive
  aidrive-mount /mnt/aidrive

To unmount:
  umount /mnt/aidrive

For help:
  aidrive-mount --help

Configuration file: $CONFIG_DIR/aidrive-mount.conf

EOF

    # Show next steps based on environment
    if [[ -n "${GENSPARK_TOKEN:-}" ]]; then
        log_success "Environment appears to be properly configured for AI Drive access"
    else
        log_warning "Environment variables not detected - this should be run in a GenSpark sandbox"
    fi
}

# Handle script interruption
trap 'log_error "Installation interrupted"; exit 1' INT TERM

# Run main function
main "$@"