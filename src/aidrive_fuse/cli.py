#!/usr/bin/env python3
"""
AI Drive FUSE CLI Module

This module provides the main entry point for the aidrive-mount command.
"""

import sys
import os
import argparse
import logging

from aidrive_fuse.config import Config, load_config
from aidrive_fuse.fuse_driver import mount_aidrive
from aidrive_fuse.utils import (
    check_fuse_availability, validate_mount_point,
    setup_signal_handlers, cleanup_stale_processes,
    check_dependencies, get_mount_status, format_size
)


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Mount AI Drive as a POSIX filesystem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic mount
  aidrive-mount /mnt/aidrive

  # Mount with custom cache settings
  aidrive-mount /mnt/aidrive --cache-size=2G --cache-ttl=600

  # Debug mode with foreground operation
  aidrive-mount /mnt/aidrive --debug --foreground

  # Mount with custom configuration
  aidrive-mount /mnt/aidrive --config=/etc/aidrive-custom.conf

  # Check mount status
  aidrive-mount --status /mnt/aidrive

  # Unmount
  umount /mnt/aidrive
        """
    )

    # Positional arguments
    parser.add_argument(
        'mountpoint',
        nargs='?',
        help='Mount point directory'
    )

    # Configuration
    parser.add_argument(
        '--config', '-c',
        help='Configuration file path'
    )

    # Cache settings
    parser.add_argument(
        '--cache-size',
        help='Cache size (e.g., 1G, 500M, 2048K)'
    )

    parser.add_argument(
        '--cache-ttl',
        type=int,
        help='Cache TTL in seconds'
    )

    parser.add_argument(
        '--cache-location',
        help='Cache directory location'
    )

    # Performance settings
    parser.add_argument(
        '--max-concurrent-ops',
        type=int,
        help='Maximum concurrent operations'
    )

    parser.add_argument(
        '--write-buffer-size',
        help='Write buffer size (e.g., 100M)'
    )

    # FUSE options
    parser.add_argument(
        '--foreground', '-f',
        action='store_true',
        help='Run in foreground (don\'t daemonize)'
    )

    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug output'
    )

    parser.add_argument(
        '--allow-other',
        action='store_true',
        help='Allow other users to access the mount'
    )

    # Logging
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Log level'
    )

    parser.add_argument(
        '--log-file',
        help='Log file path'
    )

    # Utility commands
    parser.add_argument(
        '--status',
        action='store_true',
        help='Check mount status'
    )

    parser.add_argument(
        '--check-deps',
        action='store_true',
        help='Check dependencies'
    )

    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Clean up stale processes'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='AI Drive FUSE 1.0.0'
    )

    return parser


def check_dependencies_command() -> bool:
    """Check and report dependency status."""
    print("Checking AI Drive FUSE dependencies...")
    print()

    deps = check_dependencies()
    all_ok = True

    for dep, available in deps.items():
        status = "✓ OK" if available else "✗ MISSING"
        print(f"  {dep:<20} {status}")
        if not available:
            all_ok = False

    print()

    if not all_ok:
        print("❌ Some dependencies are missing. Please install them before using AI Drive FUSE.")
        return False
    else:
        print("✅ All dependencies are available.")
        return True


def status_command(mountpoint: str) -> None:
    """Check and report mount status."""
    print(f"Checking mount status for: {mountpoint}")
    print()

    status = get_mount_status(mountpoint)

    if status.get('error'):
        print(f"❌ Error checking status: {status['error']}")
        return

    if status['mounted']:
        print("✅ Mounted")

        if status['accessible']:
            print("✅ Accessible")

            fs_info = status.get('filesystem_info', {})
            if fs_info:
                print(f"📊 Total space: {format_size(fs_info.get('total_size', 0))}")
                print(f"📊 Used space: {format_size(fs_info.get('used_size', 0))}")
                print(f"📊 Free space: {format_size(fs_info.get('free_size', 0))}")
                print(f"📊 Usage: {fs_info.get('usage_percent', 0):.1f}%")
        else:
            print("❌ Not accessible")
    else:
        print("❌ Not mounted")


def cleanup_command(mountpoint: str) -> None:
    """Clean up stale processes."""
    print(f"Cleaning up stale processes for: {mountpoint}")
    cleanup_stale_processes(mountpoint)
    print("✅ Cleanup completed")


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle utility commands
    if args.check_deps:
        success = check_dependencies_command()
        sys.exit(0 if success else 1)

    if args.status:
        if not args.mountpoint:
            print("❌ Mount point required for status check")
            sys.exit(1)
        status_command(args.mountpoint)
        sys.exit(0)

    if args.cleanup:
        if not args.mountpoint:
            print("❌ Mount point required for cleanup")
            sys.exit(1)
        cleanup_command(args.mountpoint)
        sys.exit(0)

    # Mount command requires mountpoint
    if not args.mountpoint:
        parser.print_help()
        sys.exit(1)

    mountpoint = os.path.abspath(args.mountpoint)

    try:
        # Load configuration
        config = load_config(args.config)

        # Override with command line arguments
        config = Config.from_args(args, base_config=config)
        config.mountpoint = mountpoint

        # Validate configuration
        if not config.validate():
            print("❌ Configuration validation failed")
            sys.exit(1)

        # Setup logging
        config.setup_logging()
        logger = logging.getLogger(__name__)

        # Check dependencies
        if not check_fuse_availability():
            print("❌ FUSE not available")
            sys.exit(1)

        # Validate mount point
        if not validate_mount_point(mountpoint):
            print(f"❌ Invalid mount point: {mountpoint}")
            sys.exit(1)

        # Clean up any stale processes
        cleanup_stale_processes(mountpoint)

        # Print configuration summary
        if config.debug:
            print("AI Drive FUSE Configuration:")
            for section, values in config.get_summary().items():
                print(f"  {section}:")
                for key, value in values.items():
                    print(f"    {key}: {value}")
            print()

        print(f"🚀 Mounting AI Drive at: {mountpoint}")

        if not config.foreground:
            print("💡 Running in background. Use 'umount' to unmount.")

        # Setup signal handlers for graceful shutdown
        def cleanup() -> None:
            logger.info("Shutting down AI Drive FUSE...")

        setup_signal_handlers(cleanup)

        # Mount filesystem
        mount_aidrive(mountpoint, config)

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
