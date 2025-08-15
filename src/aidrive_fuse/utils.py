"""
Utility functions for AI Drive FUSE

Common helper functions and utilities.
"""

import os
import sys
import signal
import time
import logging
from typing import Optional, Dict, Any, Callable
from pathlib import Path
import psutil


logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human readable string."""
    if size_bytes == 0:
        return "0B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size_float = float(size_bytes)
    while size_float >= 1024 and i < len(size_names) - 1:
        size_float /= 1024.0
        i += 1

    return f"{size_float:.1f}{size_names[i]}"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def ensure_directory(path: str, mode: int = 0o755) -> bool:
    """Ensure directory exists with proper permissions."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True, mode=mode)
        return True
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        return False


def is_mount_point(path: str) -> bool:
    """Check if path is a mount point."""
    try:
        path_obj = Path(path).resolve()
        parent = path_obj.parent

        # Check if device IDs differ (indicating mount point)
        return path_obj.stat().st_dev != parent.stat().st_dev
    except Exception:
        return False


def find_mount_point(path: str) -> Optional[str]:
    """Find the mount point for a given path."""
    try:
        path_obj = Path(path).resolve()

        # Walk up the directory tree
        while path_obj != path_obj.parent:
            if is_mount_point(str(path_obj)):
                return str(path_obj)
            path_obj = path_obj.parent

        return str(path_obj)  # Root directory
    except Exception:
        return None


def get_filesystem_info(path: str) -> Dict[str, Any]:
    """Get filesystem information for a path."""
    try:
        stat_info = os.statvfs(path)

        total_size = stat_info.f_blocks * stat_info.f_frsize
        free_size = stat_info.f_bavail * stat_info.f_frsize
        used_size = total_size - free_size

        return {
            'total_size': total_size,
            'used_size': used_size,
            'free_size': free_size,
            'usage_percent': (used_size / total_size * 100) if total_size > 0 else 0,
            'total_inodes': stat_info.f_files,
            'free_inodes': stat_info.f_ffree,
            'filesystem_type': 'aidrive-fuse'
        }
    except Exception as e:
        logger.error(f"Failed to get filesystem info for {path}: {e}")
        return {}


def get_process_info() -> Dict[str, Any]:
    """Get current process information."""
    try:
        process = psutil.Process()

        return {
            'pid': process.pid,
            'memory_usage': process.memory_info().rss,
            'cpu_percent': process.cpu_percent(),
            'num_threads': process.num_threads(),
            'num_fds': process.num_fds(),
            'create_time': process.create_time(),
            'status': process.status()
        }
    except Exception as e:
        logger.error(f"Failed to get process info: {e}")
        return {}


def setup_signal_handlers(cleanup_func: Callable[[], None]) -> None:
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, initiating shutdown...")
        try:
            cleanup_func()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            os._exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def check_fuse_availability() -> bool:
    """Check if FUSE is available on the system."""
    try:
        # Check if /dev/fuse exists
        if not Path('/dev/fuse').exists():
            logger.error("FUSE device /dev/fuse not found")
            return False

        # Check if fuse module is loaded
        with open('/proc/filesystems', 'r') as f:
            filesystems = f.read()
            if 'fuse' not in filesystems:
                logger.error("FUSE filesystem not supported")
                return False

        # Check permissions
        if not os.access('/dev/fuse', os.R_OK | os.W_OK):
            logger.error("No permission to access /dev/fuse")
            return False

        return True
    except Exception as e:
        logger.error(f"Failed to check FUSE availability: {e}")
        return False


def validate_mount_point(mountpoint: str) -> bool:
    """Validate mount point."""
    try:
        path = Path(mountpoint)

        # Check if path exists
        if not path.exists():
            logger.error(f"Mount point does not exist: {mountpoint}")
            return False

        # Check if it's a directory
        if not path.is_dir():
            logger.error(f"Mount point is not a directory: {mountpoint}")
            return False

        # Check if already mounted
        if is_mount_point(mountpoint):
            logger.error(f"Path already mounted: {mountpoint}")
            return False

        # Check if directory is empty
        if any(path.iterdir()):
            logger.warning(f"Mount point is not empty: {mountpoint}")

        # Check permissions
        if not os.access(mountpoint, os.R_OK | os.W_OK):
            logger.error(f"No permission to access mount point: {mountpoint}")
            return False

        return True
    except Exception as e:
        logger.error(f"Failed to validate mount point {mountpoint}: {e}")
        return False


def get_system_info() -> Dict[str, Any]:
    """Get system information."""
    try:
        return {
            'platform': os.uname().sysname,
            'release': os.uname().release,
            'machine': os.uname().machine,
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'cpu_count': os.cpu_count(),
            'memory_total': psutil.virtual_memory().total,
            'memory_available': psutil.virtual_memory().available,
            'disk_usage': {
                'total': psutil.disk_usage('/').total,
                'used': psutil.disk_usage('/').used,
                'free': psutil.disk_usage('/').free
            }
        }
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        return {}


class ProgressReporter:
    """Simple progress reporter for operations."""

    def __init__(self, total: int, description: str = "Progress"):
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()
        self.last_update = 0.0

    def update(self, increment: int = 1) -> None:
        """Update progress."""
        self.current += increment
        current_time = time.time()

        # Update at most once per second
        if current_time - self.last_update >= 1.0 or self.current >= self.total:
            self._print_progress()
            self.last_update = current_time

    def _print_progress(self) -> None:
        """Print progress bar."""
        if self.total <= 0:
            return

        percent = (self.current / self.total) * 100
        elapsed = time.time() - self.start_time

        # Estimate remaining time
        if self.current > 0:
            eta = (elapsed / self.current) * (self.total - self.current)
            eta_str = format_duration(eta)
        else:
            eta_str = "unknown"

        # Create progress bar
        bar_length = 40
        filled_length = int(bar_length * self.current // self.total)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)

        print(f"\r{self.description}: |{bar}| {percent:.1f}% ({self.current}/{self.total}) ETA: {eta_str}", end='')

        if self.current >= self.total:
            print()  # New line when complete


def cleanup_stale_processes(mount_point: str) -> None:
    """Clean up any stale FUSE processes for the mount point."""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] == 'aidrive-mount':
                    cmdline = proc.info['cmdline'] or []
                    if mount_point in cmdline:
                        logger.warning(f"Found stale process {proc.info['pid']}, terminating...")
                        proc.terminate()
                        proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
    except Exception as e:
        logger.error(f"Failed to cleanup stale processes: {e}")


def check_dependencies() -> Dict[str, bool]:
    """Check if all required dependencies are available."""
    dependencies: Dict[str, bool] = {}

    # Check Python modules
    try:
        import fuse  # type: ignore  # noqa: F401
        dependencies['fuse'] = True
    except ImportError:
        dependencies['fuse'] = False

    try:
        import psutil  # noqa: F401
        dependencies['psutil'] = True
    except ImportError:
        dependencies['psutil'] = False

    # Check system components
    dependencies['fuse_device'] = Path('/dev/fuse').exists()
    try:
        with open('/proc/filesystems', 'r') as f:
            dependencies['fuse_filesystem'] = 'fuse' in f.read()
    except (OSError, IOError):
        dependencies['fuse_filesystem'] = False

    return dependencies


def get_mount_status(mount_point: str) -> Dict[str, Any]:
    """Get detailed mount status information."""
    try:
        status = {
            'mounted': is_mount_point(mount_point),
            'mount_point': mount_point,
            'accessible': False,
            'filesystem_info': {}
        }

        if status['mounted']:
            # Check if accessible
            try:
                os.listdir(mount_point)
                status['accessible'] = True
                status['filesystem_info'] = get_filesystem_info(mount_point)
            except Exception as e:
                logger.warning(f"Mount point not accessible: {e}")

        return status
    except Exception as e:
        logger.error(f"Failed to get mount status: {e}")
        return {'mounted': False, 'error': str(e)}
