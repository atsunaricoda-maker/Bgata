# AI Drive FUSE Release v1.0.16

Generated on: 2025-08-06 13:05:22 UTC

## Package Contents

### Python Packages
- genspark_aidrive_sdk-0.1.1-py3-none-any.whl
- aidrive_fuse-1.0.16.tar.gz
- aidrive_fuse-1.0.16-py3-none-any.whl

### Installation Scripts
- check-environment.sh
- check-libfuse.sh
- mount-aidrive.sh
- install-aidrive-fuse.sh
- unmount-aidrive.sh
- mount-aidrive-async.sh

### Documentation
- README.md - Main documentation
- requirements.txt - Python dependencies
- RELEASE-INFO.md - This file
- scripts-README.md

### Configuration
- aidrive-mount.conf

## Quick Installation

1. Extract the release package
2. Run: `./scripts/install-aidrive-fuse.sh`
3. Mount: `./scripts/mount-aidrive.sh /mnt/aidrive`

## Environment Requirements

The following environment variables must be set in the GenSpark sandbox:
- `GENSPARK_TOKEN` (required)
- `GENSPARK_BASE_URL` (optional)
- `GENSPARK_AIDRIVE_API_PREFIX` (optional)
- `GENSPARK_ROUTE_IDENTIFIER` (optional)
- `GENSPARK_ENVIRONMENT_ID` (optional)

For more information, see README.md and docs/scripts-README.md
