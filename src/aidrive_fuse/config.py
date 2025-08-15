"""
Configuration Management for AI Drive FUSE

Handles configuration loading, validation, and management.
"""

import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field
import configparser


logger = logging.getLogger(__name__)


def parse_size(size_str: str) -> int:
    """Parse size string (e.g., '1G', '500M', '2048K') to bytes."""
    if not size_str:
        return 0

    size_str = size_str.upper().strip()

    # Extract number and unit
    multipliers = {
        'B': 1,
        'K': 1024,
        'M': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'T': 1024 * 1024 * 1024 * 1024
    }

    # Find the unit
    unit = 'B'
    for suffix in ['T', 'G', 'M', 'K']:
        if size_str.endswith(suffix):
            unit = suffix
            size_str = size_str[:-1]
            break

    try:
        number = float(size_str)
        return int(number * multipliers[unit])
    except ValueError:
        raise ValueError(f"Invalid size format: {size_str}")


@dataclass
class Config:
    """Configuration class for AI Drive FUSE."""

    # Cache settings
    cache_size: int = field(default=1024 * 1024 * 1024)  # 1GB default
    cache_ttl: int = 300  # 5 minutes
    cache_location: str = "/tmp/aidrive-cache"

    # Performance settings
    max_concurrent_uploads: int = 5
    max_concurrent_downloads: int = 10
    write_buffer_size: int = 100 * 1024 * 1024  # 100MB
    read_ahead_size: int = 1024 * 1024  # 1MB

    # Behavior settings
    auto_sync_interval: int = 30  # seconds
    fail_on_network_error: bool = True
    offline_mode: bool = False

    # Timeout settings (in seconds)
    sync_upload_timeout: int = 300  # 5 minutes for sync uploads
    sync_upload_timeout_per_mb: int = 2  # Additional 2 seconds per MB
    max_sync_upload_timeout: int = 1800  # Maximum 30 minutes for any file
    async_operation_timeout: int = 120  # 2 minutes for async operations

    # FUSE settings
    foreground: bool = False
    debug: bool = False
    allow_other: bool = False

    # Mount settings
    mountpoint: str = ""

    # Logging settings
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # Logging callback settings
    logging_callback_enabled: bool = False
    logging_callback_endpoint_url: str = ""
    logging_callback_strategy: str = "buffered"  # immediate | buffered
    logging_callback_immediate_levels: str = "ERROR,CRITICAL"
    logging_callback_buffer_size: int = 100
    logging_callback_flush_interval: int = 60

    @classmethod
    def from_file(cls, config_path: str) -> 'Config':
        """Load configuration from file."""
        config = cls()

        if not os.path.exists(config_path):
            logger.info(f"Config file not found: {config_path}, using defaults")
            return config

        try:
            parser = configparser.ConfigParser()
            parser.read(config_path)

            # Load cache settings
            if parser.has_section('cache'):
                cache_section = parser['cache']
                if 'size' in cache_section:
                    config.cache_size = parse_size(cache_section['size'])
                if 'ttl' in cache_section:
                    config.cache_ttl = cache_section.getint('ttl')  # type: ignore[assignment]
                if 'location' in cache_section:
                    config.cache_location = cache_section['location']

            # Load performance settings
            if parser.has_section('performance'):
                perf_section = parser['performance']
                if 'max_concurrent_uploads' in perf_section:
                    config.max_concurrent_uploads = perf_section.getint(
                        'max_concurrent_uploads')  # type: ignore[assignment]
                if 'max_concurrent_downloads' in perf_section:
                    config.max_concurrent_downloads = perf_section.getint(
                        'max_concurrent_downloads')  # type: ignore[assignment]
                if 'write_buffer_size' in perf_section:
                    config.write_buffer_size = parse_size(perf_section['write_buffer_size'])
                if 'read_ahead_size' in perf_section:
                    config.read_ahead_size = parse_size(perf_section['read_ahead_size'])

            # Load behavior settings
            if parser.has_section('behavior'):
                behavior_section = parser['behavior']
                if 'auto_sync_interval' in behavior_section:
                    config.auto_sync_interval = behavior_section.getint(
                        'auto_sync_interval')  # type: ignore[assignment]
                if 'fail_on_network_error' in behavior_section:
                    config.fail_on_network_error = behavior_section.getboolean(
                        'fail_on_network_error')  # type: ignore[assignment]
                if 'offline_mode' in behavior_section:
                    config.offline_mode = behavior_section.getboolean('offline_mode')  # type: ignore[assignment]

            # Load timeout settings
            if parser.has_section('timeouts'):
                timeout_section = parser['timeouts']
                if 'sync_upload_timeout' in timeout_section:
                    config.sync_upload_timeout = timeout_section.getint(
                        'sync_upload_timeout')  # type: ignore[assignment]
                if 'sync_upload_timeout_per_mb' in timeout_section:
                    config.sync_upload_timeout_per_mb = timeout_section.getint(
                        'sync_upload_timeout_per_mb')  # type: ignore[assignment]
                if 'max_sync_upload_timeout' in timeout_section:
                    config.max_sync_upload_timeout = timeout_section.getint(
                        'max_sync_upload_timeout')  # type: ignore[assignment]
                if 'async_operation_timeout' in timeout_section:
                    config.async_operation_timeout = timeout_section.getint(
                        'async_operation_timeout')  # type: ignore[assignment]

            # Load FUSE settings
            if parser.has_section('fuse'):
                fuse_section = parser['fuse']
                if 'foreground' in fuse_section:
                    config.foreground = fuse_section.getboolean('foreground')  # type: ignore[assignment]
                if 'debug' in fuse_section:
                    config.debug = fuse_section.getboolean('debug')  # type: ignore[assignment]
                if 'allow_other' in fuse_section:
                    config.allow_other = fuse_section.getboolean('allow_other')  # type: ignore[assignment]

            # Load logging settings
            if parser.has_section('logging'):
                log_section = parser['logging']
                if 'level' in log_section:
                    config.log_level = log_section['level'].upper()
                if 'file' in log_section:
                    config.log_file = log_section['file']

            # Load logging callback settings
            if parser.has_section('logging_callback'):
                callback_section = parser['logging_callback']
                if 'enabled' in callback_section:
                    config.logging_callback_enabled = callback_section.getboolean('enabled')  # type: ignore[assignment]
                if 'endpoint_url' in callback_section:
                    config.logging_callback_endpoint_url = callback_section['endpoint_url']
                if 'strategy' in callback_section:
                    config.logging_callback_strategy = callback_section['strategy']
                if 'immediate_levels' in callback_section:
                    config.logging_callback_immediate_levels = callback_section['immediate_levels']
                if 'buffer_size' in callback_section:
                    config.logging_callback_buffer_size = callback_section.getint(
                        'buffer_size')  # type: ignore[assignment]
                if 'flush_interval' in callback_section:
                    config.logging_callback_flush_interval = callback_section.getint(
                        'flush_interval')  # type: ignore[assignment]

            logger.info(f"Configuration loaded from {config_path}")

        except Exception as e:
            logger.error(f"Failed to load configuration from {config_path}: {e}")
            logger.info("Using default configuration")

        return config

    @classmethod
    def from_args(cls, args: Any, base_config: Optional['Config'] = None) -> 'Config':
        """Create configuration from command line arguments, optionally overriding base config."""
        if base_config is not None:
            # Start with base config
            config = base_config
        else:
            # Create default config
            config = cls()

        # Override with command line arguments
        if hasattr(args, 'cache_size') and args.cache_size:
            config.cache_size = parse_size(args.cache_size)
        if hasattr(args, 'cache_ttl') and args.cache_ttl:
            config.cache_ttl = args.cache_ttl
        if hasattr(args, 'cache_location') and args.cache_location:
            config.cache_location = args.cache_location
        if hasattr(args, 'max_concurrent_ops') and args.max_concurrent_ops:
            config.max_concurrent_uploads = args.max_concurrent_ops // 2
            config.max_concurrent_downloads = args.max_concurrent_ops
        if hasattr(args, 'write_buffer_size') and args.write_buffer_size:
            config.write_buffer_size = parse_size(args.write_buffer_size)
        if hasattr(args, 'foreground') and args.foreground:
            config.foreground = args.foreground
        if hasattr(args, 'debug') and args.debug:
            config.debug = args.debug
        if hasattr(args, 'allow_other') and args.allow_other:
            config.allow_other = args.allow_other
        if hasattr(args, 'log_level') and args.log_level:
            config.log_level = args.log_level.upper()
        if hasattr(args, 'log_file') and args.log_file:
            config.log_file = args.log_file

        return config

    def validate(self) -> bool:
        """Validate configuration values."""
        errors = []

        # Validate cache size
        if self.cache_size <= 0:
            errors.append("Cache size must be positive")

        # Validate cache TTL
        if self.cache_ttl < 0:
            errors.append("Cache TTL must be non-negative")

        # Validate cache location
        try:
            Path(self.cache_location).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Invalid cache location: {e}")

        # Validate concurrency limits
        if self.max_concurrent_uploads <= 0:
            errors.append("Max concurrent uploads must be positive")
        if self.max_concurrent_downloads <= 0:
            errors.append("Max concurrent downloads must be positive")

        # Validate buffer sizes
        if self.write_buffer_size <= 0:
            errors.append("Write buffer size must be positive")
        if self.read_ahead_size <= 0:
            errors.append("Read ahead size must be positive")

        # Validate sync interval
        if self.auto_sync_interval < 0:
            errors.append("Auto sync interval must be non-negative")

        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level not in valid_levels:
            errors.append(f"Invalid log level: {self.log_level}")

        if errors:
            for error in errors:
                logger.error(f"Configuration validation error: {error}")
            return False

        return True

    def setup_logging(self) -> None:
        """Setup logging based on configuration."""
        level = getattr(logging, self.log_level, logging.INFO)

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Setup root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # Add file handler if specified
        if self.log_file:
            try:
                # Ensure log directory exists
                Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)

                file_handler = logging.FileHandler(self.log_file)
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)

                logger.info(f"Logging to file: {self.log_file}")
            except Exception as e:
                logger.error(f"Failed to setup file logging: {e}")

        # Setup logging callback if enabled
        self._setup_logging_callback()

    def _setup_logging_callback(self) -> None:
        """Setup logging callback handler if enabled."""
        if not self.logging_callback_enabled:
            return

        try:
            from .logging_callback import setup_logging_callback
            setup_logging_callback(self)
        except ImportError as e:
            logger.warning(f"Failed to import logging callback: {e}")
        except Exception as e:
            logger.error(f"Failed to setup logging callback: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get configuration summary."""
        return {
            'cache': {
                'size': f"{self.cache_size / (1024*1024*1024):.1f}GB",
                'ttl': f"{self.cache_ttl}s",
                'location': self.cache_location
            },
            'performance': {
                'max_concurrent_uploads': self.max_concurrent_uploads,
                'max_concurrent_downloads': self.max_concurrent_downloads,
                'write_buffer_size': f"{self.write_buffer_size / (1024*1024):.1f}MB",
                'read_ahead_size': f"{self.read_ahead_size / (1024*1024):.1f}MB"
            },
            'behavior': {
                'auto_sync_interval': f"{self.auto_sync_interval}s",
                'fail_on_network_error': self.fail_on_network_error,
                'offline_mode': self.offline_mode
            },
            'fuse': {
                'foreground': self.foreground,
                'debug': self.debug,
                'allow_other': self.allow_other
            },
            'logging': {
                'level': self.log_level,
                'file': self.log_file or 'console only'
            }
        }

    def save_to_file(self, config_path: str) -> None:
        """Save current configuration to file."""
        try:
            parser = configparser.ConfigParser()

            # Cache section
            parser.add_section('cache')
            parser.set('cache', 'size', f"{self.cache_size // (1024*1024*1024)}G")
            parser.set('cache', 'ttl', str(self.cache_ttl))
            parser.set('cache', 'location', self.cache_location)

            # Performance section
            parser.add_section('performance')
            parser.set('performance', 'max_concurrent_uploads', str(self.max_concurrent_uploads))
            parser.set('performance', 'max_concurrent_downloads', str(self.max_concurrent_downloads))
            parser.set('performance', 'write_buffer_size', f"{self.write_buffer_size // (1024*1024)}M")
            parser.set('performance', 'read_ahead_size', f"{self.read_ahead_size // (1024*1024)}M")

            # Behavior section
            parser.add_section('behavior')
            parser.set('behavior', 'auto_sync_interval', str(self.auto_sync_interval))
            parser.set('behavior', 'fail_on_network_error', str(self.fail_on_network_error))
            parser.set('behavior', 'offline_mode', str(self.offline_mode))

            # Timeout section
            parser.add_section('timeouts')
            parser.set('timeouts', 'sync_upload_timeout', str(self.sync_upload_timeout))
            parser.set('timeouts', 'sync_upload_timeout_per_mb', str(self.sync_upload_timeout_per_mb))
            parser.set('timeouts', 'max_sync_upload_timeout', str(self.max_sync_upload_timeout))
            parser.set('timeouts', 'async_operation_timeout', str(self.async_operation_timeout))

            # FUSE section
            parser.add_section('fuse')
            parser.set('fuse', 'foreground', str(self.foreground))
            parser.set('fuse', 'debug', str(self.debug))
            parser.set('fuse', 'allow_other', str(self.allow_other))

            # Logging section
            parser.add_section('logging')
            parser.set('logging', 'level', self.log_level)
            if self.log_file:
                parser.set('logging', 'file', self.log_file)

            # Logging callback section
            parser.add_section('logging_callback')
            parser.set('logging_callback', 'enabled', str(self.logging_callback_enabled))
            parser.set('logging_callback', 'endpoint_url', self.logging_callback_endpoint_url)
            parser.set('logging_callback', 'strategy', self.logging_callback_strategy)
            parser.set('logging_callback', 'immediate_levels', self.logging_callback_immediate_levels)
            parser.set('logging_callback', 'buffer_size', str(self.logging_callback_buffer_size))
            parser.set('logging_callback', 'flush_interval', str(self.logging_callback_flush_interval))

            # Ensure directory exists
            Path(config_path).parent.mkdir(parents=True, exist_ok=True)

            # Write configuration
            with open(config_path, 'w') as f:
                parser.write(f)

            logger.info(f"Configuration saved to {config_path}")

        except Exception as e:
            logger.error(f"Failed to save configuration to {config_path}: {e}")

    def calculate_upload_timeout(self, file_size_bytes: int) -> float:
        """
        Calculate appropriate upload timeout based on file size.

        Args:
            file_size_bytes: Size of file in bytes

        Returns:
            Timeout in seconds, considering base timeout + per-MB overhead
        """
        # Convert bytes to MB
        file_size_mb = file_size_bytes / (1024 * 1024)

        # Calculate timeout: base + (size_in_mb * per_mb_timeout)
        calculated_timeout = self.sync_upload_timeout + (file_size_mb * self.sync_upload_timeout_per_mb)

        # Ensure we don't exceed maximum timeout
        return min(calculated_timeout, self.max_sync_upload_timeout)


def get_default_config_paths() -> list[str]:
    """Get list of default configuration file paths."""
    paths = []

    # System-wide config
    paths.append('/etc/aidrive-mount.conf')

    # User-specific config
    if 'HOME' in os.environ:
        paths.append(os.path.join(os.environ['HOME'], '.config', 'aidrive-mount.conf'))
        paths.append(os.path.join(os.environ['HOME'], '.aidrive-mount.conf'))

    # Current directory
    paths.append('./aidrive-mount.conf')

    return paths


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or defaults."""
    if config_path:
        # Use specific config file
        return Config.from_file(config_path)

    # Try default locations
    for path in get_default_config_paths():
        if os.path.exists(path):
            logger.info(f"Using config file: {path}")
            return Config.from_file(path)

    # No config file found, use defaults
    logger.info("No configuration file found, using defaults")
    return Config()
