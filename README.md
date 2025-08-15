# AI Drive FUSE Filesystem

A FUSE-based filesystem implementation that mounts GenSpark AI Drive as a standard POSIX filesystem, enabling direct file operations without SDK API calls.

## Features

- **POSIX Compliance**: Standard filesystem operations (`ls`, `cp`, `mv`, `mkdir`, etc.)
- **Intelligent Caching**: Metadata and data caching with configurable TTL
- **Async Operations**: Concurrent upload/download with operation queuing
- **Error Resilience**: Network error recovery with exponential backoff
- **Performance Optimization**: Read-ahead, write buffering, and background sync
- **Flexible Configuration**: File-based and command-line configuration

## Architecture

```
User Applications (POSIX calls)
         ↓
    Linux VFS Layer
         ↓
    FUSE Kernel Module
         ↓
   AIDrive FUSE Daemon
         ↓
  GenSpark AIDrive SDK
         ↓
  GenSpark AIDrive API
```

## Installation

### Prerequisites

```bash
# System dependencies
sudo apt-get update
sudo apt-get install fuse3 libfuse3-dev python3-dev python3-pip

# Add user to fuse group
sudo usermod -a -G fuse $USER
# Log out and back in for group changes to take effect
```

### Install from Source

```bash
# Clone or extract the aidrive-fuse package
cd aidrive-fuse

# Install Python dependencies
pip3 install -r requirements.txt

# Install the package
sudo pip3 install .

# Or install in development mode
pip3 install -e .
```

### Install Binary Package

```bash
# Install from package (when available)
sudo pip3 install aidrive-fuse

# Install system files
sudo cp bin/aidrive-mount /usr/local/bin/
sudo cp etc/aidrive-mount.conf /etc/
sudo cp systemd/aidrive-mount@.service /lib/systemd/system/
sudo systemctl daemon-reload
```

## Quick Start

### Basic Usage

```bash
# Create mount point
sudo mkdir -p /mnt/aidrive

# Mount AI Drive
sudo aidrive-mount /mnt/aidrive

# Use standard filesystem operations
ls -la /mnt/aidrive/
echo "Hello World" > /mnt/aidrive/test.txt
cp local_file.txt /mnt/aidrive/
mkdir /mnt/aidrive/new_folder

# Unmount
sudo umount /mnt/aidrive
```

### Advanced Usage

```bash
# Mount with custom cache settings
aidrive-mount /mnt/aidrive --cache-size=2G --cache-ttl=600

# Debug mode
aidrive-mount /mnt/aidrive --debug --foreground

# Custom configuration file
aidrive-mount /mnt/aidrive --config=/etc/aidrive-custom.conf

# Check mount status
aidrive-mount --status /mnt/aidrive

# Check dependencies
aidrive-mount --check-deps
```

## Configuration

### Configuration File

Default location: `/etc/aidrive-mount.conf`

```ini
[cache]
size = 1G
ttl = 300
location = /tmp/aidrive-cache

[performance]
max_concurrent_uploads = 5
max_concurrent_downloads = 10
write_buffer_size = 100M
read_ahead_size = 1M

[behavior]
auto_sync_interval = 30
fail_on_network_error = true
offline_mode = false

[fuse]
foreground = false
debug = false
allow_other = false

[logging]
level = INFO
# file = /var/log/aidrive-mount.log
```

### Command Line Options

```bash
aidrive-mount [OPTIONS] MOUNTPOINT

Options:
  --config PATH               Configuration file path
  --cache-size SIZE          Cache size (e.g., 1G, 500M)
  --cache-ttl SECONDS        Cache TTL in seconds
  --cache-location PATH      Cache directory location
  --max-concurrent-ops N     Maximum concurrent operations
  --write-buffer-size SIZE   Write buffer size
  --foreground, -f           Run in foreground
  --debug, -d                Enable debug output
  --allow-other              Allow other users to access
  --log-level LEVEL          Log level (DEBUG/INFO/WARNING/ERROR)
  --log-file PATH            Log file path
  --status                   Check mount status
  --check-deps               Check dependencies
  --cleanup                  Clean up stale processes
```

## System Service

### Using systemd

```bash
# Enable and start service for /mnt/aidrive
sudo systemctl enable aidrive-mount@mnt-aidrive.service
sudo systemctl start aidrive-mount@mnt-aidrive.service

# Check status
sudo systemctl status aidrive-mount@mnt-aidrive.service

# Stop and disable
sudo systemctl stop aidrive-mount@mnt-aidrive.service
sudo systemctl disable aidrive-mount@mnt-aidrive.service
```

### Auto-mount on Boot

Add to `/etc/fstab`:

```
# AI Drive FUSE mount
aidrive-fuse /mnt/aidrive fuse user,noauto,exec,_netdev 0 0
```

## Performance Tuning

### Cache Settings

- **Cache Size**: Larger cache improves performance but uses more disk space
- **Cache TTL**: Shorter TTL ensures fresher data but increases API calls
- **Cache Location**: Use fast storage (SSD) for better performance

### Concurrency Settings

- **Upload Concurrency**: Increase for better upload performance (mind API limits)
- **Download Concurrency**: Higher values improve large file operations
- **Write Buffer**: Larger buffers reduce API calls but use more memory

### Network Optimization

```bash
# For high-latency networks
aidrive-mount /mnt/aidrive --cache-ttl=3600 --write-buffer-size=500M

# For fast networks
aidrive-mount /mnt/aidrive --max-concurrent-ops=20 --cache-ttl=60
```

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Mount fails | Missing FUSE permissions | Add user to `fuse` group |
| Slow performance | Network latency | Increase cache size/TTL |
| Cache full | Large files | Configure cache size or enable auto-cleanup |
| Authentication errors | SDK token expired | Check VM authentication setup |

### Debug Mode

```bash
# Enable debug logging
aidrive-mount /mnt/aidrive --debug --foreground

# Check FUSE operations
strace -e trace=file ls /mnt/aidrive/

# Monitor cache status
ls -la /tmp/aidrive-cache/
```

### Log Analysis

```bash
# View logs
tail -f /var/log/aidrive-mount.log

# Check system logs
journalctl -u aidrive-mount@mnt-aidrive.service -f
```

## API Reference

### POSIX Operation Mapping

| POSIX Operation | AI Drive SDK Method | Implementation |
|-----------------|-------------------|----------------|
| `open()` | `download_file()` | Cache file locally |
| `read()` | Local cache read | Stream from cache |
| `write()` | Buffer locally | Defer upload until sync |
| `readdir()` | `list_files()` | Cache directory listings |
| `mkdir()` | `create_directory()` | Direct API call |
| `unlink()` | `delete_item()` | Direct API call with cache invalidation |
| `rename()` | `move_item()` | Direct API call with cache update |

### Cache Behavior

- **Read Cache**: LRU eviction with configurable size limit
- **Write Cache**: Write-through with background sync
- **Metadata Cache**: TTL-based expiration
- **Consistency**: Eventually consistent with remote state

## Development

### Project Structure

```
aidrive-fuse/
├── aidrive_fuse/           # Main package
│   ├── __init__.py
│   ├── fuse_driver.py      # Core FUSE implementation
│   ├── cache_manager.py    # Cache management
│   ├── operation_queue.py  # Async operations
│   ├── config.py          # Configuration
│   └── utils.py           # Utilities
├── bin/aidrive-mount      # Command line tool
├── etc/aidrive-mount.conf # Default configuration
├── systemd/               # systemd service files
├── tests/                 # Test suite
└── setup.py              # Installation script
```

### Testing

```bash
# Install development dependencies
pip3 install -e .[dev]

# Run tests
pytest tests/

# Run with coverage
pytest --cov=aidrive_fuse tests/

# Type checking
mypy aidrive_fuse/

# Code formatting
black aidrive_fuse/
flake8 aidrive_fuse/
```

## Security Considerations

- **Authentication**: Uses pre-configured AI Drive SDK authentication
- **Permissions**: Supports POSIX permission simulation
- **Cache Security**: Restricts cache access to mounting user
- **Network Security**: All communications via HTTPS API

## Limitations

- **No Hard Links**: AI Drive doesn't support hard links
- **No Symlinks**: Symbolic links not supported (could be added)
- **No Extended Attributes**: xattr support not implemented
- **No Locking**: File locking not supported across network
- **Eventual Consistency**: Changes may not be immediately visible

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and bug reports, please use the GitHub issue tracker or contact support@genspark.com.