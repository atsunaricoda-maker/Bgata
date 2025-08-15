# AI Drive FUSE Mount Scripts

This directory contains scripts for installing and mounting AI Drive as a POSIX filesystem in GenSpark sandbox environments.

## Scripts Overview

| Script | Purpose | Usage |
|--------|---------|-------|
| `install-aidrive-fuse.sh` | Install AI Drive FUSE package and dependencies | `./install-aidrive-fuse.sh` |
| `mount-aidrive.sh` | Mount AI Drive filesystem | `./mount-aidrive.sh [mount_point]` |
| `unmount-aidrive.sh` | Safely unmount AI Drive filesystem | `./unmount-aidrive.sh [mount_point]` |
| `check-environment.sh` | Check environment readiness | `./check-environment.sh` |

## Quick Start

```bash
# 1. Check environment
./check-environment.sh

# 2. Install AI Drive FUSE (run once)
./install-aidrive-fuse.sh

# 3. Mount AI Drive
./mount-aidrive.sh /mnt/aidrive

# 4. Use as regular filesystem
ls /mnt/aidrive/
echo "Hello World" > /mnt/aidrive/test.txt
cp localfile.txt /mnt/aidrive/

# 5. Unmount when done
./unmount-aidrive.sh /mnt/aidrive
```

## Environment Variables

The following environment variables are automatically injected by the GenSpark sandbox:

### Required
- `GENSPARK_TOKEN` - Authentication token for AI Drive API

### Optional
- `GENSPARK_BASE_URL` - API base URL (default: https://www.genspark.ai)
- `GENSPARK_AIDRIVE_API_PREFIX` - API prefix (default: /api/aidrive)
- `GENSPARK_ROUTE_IDENTIFIER` - Route identifier for special network routing
- `GENSPARK_ENVIRONMENT_ID` - Environment ID for current running environment

## Installation Script

### `install-aidrive-fuse.sh`

Installs the AI Drive FUSE package and all dependencies.

**Features:**
- Automatic system/user mode detection
- Dependency checking and installation
- Environment variable validation
- SystemD service installation (system mode)

**Usage:**
```bash
# System-wide installation (requires sudo)
sudo ./install-aidrive-fuse.sh

# User installation
./install-aidrive-fuse.sh
```

**What it installs:**
- Python dependencies (fusepy, psutil)
- AI Drive FUSE package
- aidrive-mount command
- Configuration files
- SystemD service (if root)

## Mount Script

### `mount-aidrive.sh`

Mounts AI Drive as a POSIX filesystem.

**Features:**
- Environment validation
- Automatic mount point creation
- Configurable cache settings
- Debug and foreground modes
- Comprehensive error checking

**Usage:**
```bash
# Basic mount
./mount-aidrive.sh /mnt/aidrive

# Custom cache settings
./mount-aidrive.sh --cache-size=2G --cache-ttl=600 /mnt/aidrive

# Debug mode
./mount-aidrive.sh --debug --foreground /mnt/aidrive

# Dry run (show what would be done)
./mount-aidrive.sh --dry-run /mnt/aidrive
```

**Options:**
- `-f, --force` - Force mount even if directory not empty
- `--foreground` - Run in foreground (don't daemonize)
- `--debug` - Enable debug output
- `-c, --config FILE` - Use custom configuration file
- `--cache-size SIZE` - Cache size (e.g., 1G, 500M)
- `--cache-ttl SEC` - Cache TTL in seconds
- `--dry-run` - Show commands without executing

## Unmount Script

### `unmount-aidrive.sh`

Safely unmounts AI Drive filesystem.

**Features:**
- Process detection and termination
- Force unmount capability
- Cache cleanup option
- Comprehensive status checking

**Usage:**
```bash
# Basic unmount
./unmount-aidrive.sh /mnt/aidrive

# Force unmount with cleanup
./unmount-aidrive.sh --force --cleanup /mnt/aidrive

# Kill processes and clean cache
./unmount-aidrive.sh --kill --cleanup /mnt/aidrive
```

**Options:**
- `-f, --force` - Force unmount (lazy unmount)
- `-k, --kill` - Kill processes using the mount point
- `-c, --cleanup` - Clean up cache after unmount

## Environment Check Script

### `check-environment.sh`

Validates the environment for AI Drive FUSE compatibility.

**Features:**
- System prerequisites checking
- Python package validation
- Environment variable verification
- AI Drive connectivity testing
- Mount point validation

**Usage:**
```bash
./check-environment.sh
```

**Exit codes:**
- `0` - All checks passed
- `1` - Critical failures found
- `2` - Warnings present but usable

## Configuration

### Default Mount Points

The scripts use these default mount points in order of preference:
1. `/mnt/aidrive` (recommended)
2. `/tmp/aidrive` (temporary)
3. `$HOME/aidrive` (user directory)

### Cache Settings

Default cache configuration:
- **Size**: 1GB
- **TTL**: 300 seconds (5 minutes)
- **Location**: `/tmp/aidrive-cache`

### Configuration File

The mount tool uses configuration files in this order:
1. Specified via `--config` option
2. `/etc/aidrive-mount.conf` (system-wide)
3. `$HOME/.config/aidrive-mount.conf` (user)
4. `$HOME/.aidrive-mount.conf` (user legacy)
5. `./aidrive-mount.conf` (current directory)

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "FUSE device not found" | FUSE not installed | `sudo apt-get install fuse3` |
| "Permission denied" | User not in fuse group | `sudo usermod -a -G fuse $USER` |
| "Mount failed" | Environment variables missing | Check with `./check-environment.sh` |
| "Authentication failed" | Invalid token | Verify `GENSPARK_TOKEN` is set |
| "Directory not empty" | Mount point has files | Use `--force` or empty directory |

### Debug Mode

Enable debug mode for detailed logging:

```bash
./mount-aidrive.sh --debug --foreground /mnt/aidrive
```

### Logs

Check logs for issues:
```bash
# System logs
journalctl -u aidrive-mount@mnt-aidrive.service -f

# Application logs (if configured)
tail -f /var/log/aidrive-mount.log
```

### Manual Mount

If scripts fail, try manual mounting:

```bash
# Check environment first
./check-environment.sh

# Manual mount
aidrive-mount /mnt/aidrive --debug --foreground
```

## Advanced Usage

### SystemD Service

For persistent mounts across reboots:

```bash
# Enable service for /mnt/aidrive
sudo systemctl enable aidrive-mount@mnt-aidrive.service
sudo systemctl start aidrive-mount@mnt-aidrive.service

# Check status
sudo systemctl status aidrive-mount@mnt-aidrive.service
```

### Custom Configuration

Create custom configuration file:

```bash
cp /etc/aidrive-mount.conf ./my-config.conf
# Edit settings
./mount-aidrive.sh --config=./my-config.conf /mnt/aidrive
```

### Performance Tuning

For high-performance scenarios:

```bash
./mount-aidrive.sh \
  --cache-size=4G \
  --cache-ttl=3600 \
  /mnt/aidrive
```

## Integration with Release Pipeline

These scripts are automatically packaged with AI Drive FUSE releases through the GitHub Actions workflow:

1. **Build**: Package is built with all dependencies
2. **Package**: Scripts are included in release artifact
3. **Release**: Scripts are available in GitHub releases
4. **Deploy**: Extract and run in sandbox environment

### Automated Deployment

```bash
# Download release
wget https://github.com/genspark/gen-spark/releases/download/aidrive-fuse-v1.0.0/aidrive-fuse-1.0.0.tar.gz

# Extract
tar -xzf aidrive-fuse-1.0.0.tar.gz
cd aidrive-fuse-1.0.0

# Install and mount
./scripts/install-aidrive-fuse.sh
./scripts/mount-aidrive.sh /mnt/aidrive
```

## Support

For issues with these scripts:

1. Run `./check-environment.sh` to diagnose problems
2. Check the [AI Drive FUSE documentation](../aidrive-fuse/README.md)
3. Review GitHub Issues for known problems
4. Contact support with environment check output