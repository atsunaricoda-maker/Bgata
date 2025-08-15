#!/bin/bash
set -euo pipefail

# AI Drive FUSE Installation Script for Docker Image Build
# This script installs system dependencies and packages, but does NOT mount
# Mounting happens later in sandbox with user-specific tokens

echo "🚀 AI Drive FUSE Installation"
echo "============================="

# Check if we're in the right directory
if [[ ! -f "VERSION" ]] || [[ ! -d "scripts" ]]; then
    echo "❌ Error: This script must be run from the AI Drive FUSE release directory"
    echo "Make sure you've extracted the release package and are in the correct directory."
    exit 1
fi

VERSION=$(cat VERSION)
echo "📦 Installing AI Drive FUSE $VERSION for Docker image"
echo ""

# Step 1: Install libfuse system dependencies
echo "🔧 Step 1: Installing libfuse system dependencies..."
echo "  Updating package lists..."
sudo apt-get update -y

echo "  Installing FUSE packages..."
sudo apt-get install -y fuse libfuse2 libfuse-dev

echo "  Updating library cache..."
sudo ldconfig

echo "  Note: FUSE device permissions (/dev/fuse) will be set during mounting"

echo "✅ Step 1 completed: System dependencies installed"
echo ""

# Step 2: Install Python dependencies and AI Drive packages
echo "🐍 Step 2: Installing Python packages..."
echo "  Installing base Python packages..."
pip3 install fusepy psutil

# Install AI Drive packages from local wheels
if ls genspark_aidrive_sdk*.whl >/dev/null 2>&1; then
    echo "  Installing genspark-aidrive-sdk..."
    pip3 install genspark_aidrive_sdk*.whl
else
    echo "  ❌ genspark-aidrive-sdk wheel not found"
    exit 1
fi

if ls aidrive_fuse*.whl >/dev/null 2>&1; then
    echo "  Installing aidrive-fuse..."
    pip3 install aidrive_fuse*.whl
else
    echo "  ❌ aidrive-fuse wheel not found"
    exit 1
fi

echo "✅ Step 2 completed: Python packages installed"
echo ""

# Step 3: Prepare mount point directory
echo "📁 Step 3: Preparing default mount point..."
MOUNT_POINT="/mnt/aidrive"

echo "  Creating mount directory: $MOUNT_POINT"
sudo mkdir -p "$MOUNT_POINT"

echo "  Setting mount point permissions..."
sudo chmod 755 "$MOUNT_POINT"

echo "✅ Step 3 completed: Mount point prepared"
echo ""

# Step 4: Verify installation
echo "🔍 Step 4: Verifying installation..."

# Check if aidrive-mount command is available
if command -v aidrive-mount &> /dev/null; then
    echo "  ✅ aidrive-mount command available"
else
    echo "  ⚠️ aidrive-mount command not found (may be OK)"
fi

# Check Python imports
if python3 -c "import aidrive_fuse" 2>/dev/null; then
    echo "  ✅ aidrive_fuse Python package available"
else
    echo "  ❌ aidrive_fuse Python package not found"
    exit 1
fi

if python3 -c "import genspark_aidrive_sdk" 2>/dev/null; then
    echo "  ✅ genspark_aidrive_sdk Python package available"
else
    echo "  ❌ genspark_aidrive_sdk Python package not found"
    exit 1
fi

echo "✅ Step 4 completed: Installation verified"
echo ""

# Installation summary
echo "📋 Installation Complete!"
echo ""
echo "✅ System dependencies (libfuse) installed"
echo "✅ Python packages (aidrive_fuse, genspark_aidrive_sdk) installed"
echo "✅ Default mount point prepared: $MOUNT_POINT"
echo "✅ Installation verified"
echo ""

echo "🎉 AI Drive FUSE is ready for use!"
echo ""
echo "📌 Usage in Sandbox:"
echo ""
echo "When running in a GenSpark sandbox with user tokens:"
echo ""
echo "To mount user's AI Drive:"
echo "  ./scripts/mount-aidrive.sh $MOUNT_POINT"
echo ""
echo "To mount with background daemon:"
echo "  ./scripts/mount-aidrive.sh $MOUNT_POINT"
echo ""
echo "Required environment variables (set by sandbox):"
echo "  GENSPARK_TOKEN - User's authentication token"
echo "  GENSPARK_BASE_URL - API base URL"
echo "  GENSPARK_AIDRIVE_API_PREFIX - API prefix (/api/aidrive)"
echo ""
echo "For help:"
echo "  ./scripts/mount-aidrive.sh --help"
echo ""
