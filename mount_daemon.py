#!/usr/bin/env python3
"""
AI Drive FUSE daemon script - Enhanced version with improved error handling
and better process management.
"""
import os
import sys
import argparse
import threading
import time
import signal
import subprocess
import logging
import atexit
from typing import TYPE_CHECKING, Optional, Dict, Any
from pathlib import Path

if TYPE_CHECKING:
    from aidrive_fuse.config import Config
    from aidrive_fuse.fuse_driver import AIDriveFUSE

# Configure logging for daemon
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Add file handler if needed
    ]
)
logger = logging.getLogger(__name__)


class MountDaemon:
    """Enhanced FUSE mount daemon with better process management."""
    
    def __init__(self):
        self.stop_event = threading.Event()
        self.mount_thread: Optional[threading.Thread] = None
        self.fuse_driver: Optional["AIDriveFUSE"] = None
        self.config: Optional["Config"] = None
        self.pid_file: Optional[Path] = None
        
    def create_pid_file(self, mountpoint: str) -> None:
        """Create PID file for daemon management."""
        try:
            # Create PID file in /tmp with mount point name
            mount_name = mountpoint.replace('/', '_').strip('_')
            pid_filename = f"aidrive_daemon_{mount_name}.pid"
            self.pid_file = Path(f"/tmp/{pid_filename}")
            
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            logger.info(f"Created PID file: {self.pid_file}")
            
            # Register cleanup on exit
            atexit.register(self.cleanup_pid_file)
            
        except Exception as e:
            logger.warning(f"Could not create PID file: {e}")
    
    def cleanup_pid_file(self) -> None:
        """Clean up PID file on exit."""
        if self.pid_file and self.pid_file.exists():
            try:
                self.pid_file.unlink()
                logger.info(f"Cleaned up PID file: {self.pid_file}")
            except Exception as e:
                logger.warning(f"Could not remove PID file: {e}")

    def mount_async(self, config: "Config", fuse_driver: "AIDriveFUSE") -> None:
        """Run FUSE mount in a separate thread with enhanced error handling."""
        try:
            from fuse import FUSE  # type: ignore

            logger.info("🔧 Starting FUSE mount in background thread...")
            
            # Check if mount point is already in use
            if self.is_already_mounted(config.mountpoint):
                logger.error(f"Mount point {config.mountpoint} is already in use")
                self.stop_event.set()
                return

            # This will block in the thread until unmounted
            FUSE(fuse_driver, config.mountpoint,
                 foreground=True,  # Always foreground in daemon mode
                 debug=config.debug,
                 allow_other=True,
                 auto_unmount=True)  # Enable auto unmount on exit

        except ImportError as e:
            logger.error(f"❌ FUSE library not available: {e}")
            logger.error("Install FUSE with: sudo apt-get install fuse3 libfuse3-dev")
        except PermissionError as e:
            logger.error(f"❌ Permission denied for mount: {e}")
            logger.error("Try running with sudo or add user to fuse group")
        except Exception as e:
            logger.error(f"❌ FUSE mount failed in thread: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        finally:
            # Signal that the mount has stopped
            logger.info("FUSE mount thread terminating")
            self.stop_event.set()
    
    def is_already_mounted(self, mountpoint: str) -> bool:
        """Check if mountpoint is already mounted."""
        try:
            result = subprocess.run(
                ["mountpoint", "-q", mountpoint],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


    def setup_signal_handlers(self) -> None:
        """Set up enhanced signal handlers for graceful shutdown."""
        def signal_handler(signum: int, frame: object) -> None:
            signal_name = signal.Signals(signum).name
            logger.info(f"\n🛑 Received {signal_name} signal, initiating graceful shutdown...")
            
            # Start shutdown process
            self.shutdown_gracefully()
        
        # Register handlers for common termination signals
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Termination request
        # SIGUSR1 for reload (future enhancement)
        signal.signal(signal.SIGUSR1, lambda s, f: logger.info("Received reload signal (not implemented)"))
    
    def shutdown_gracefully(self) -> None:
        """Perform graceful shutdown of the daemon."""
        logger.info("Starting graceful shutdown process...")
        
        # Set stop event to signal all threads
        self.stop_event.set()
        
        # Try to unmount filesystem gracefully
        unmount_success = self.unmount_filesystem()
        
        # Wait for mount thread to finish
        if self.mount_thread and self.mount_thread.is_alive():
            logger.info("Waiting for mount thread to finish...")
            self.mount_thread.join(timeout=15)
            
            if self.mount_thread.is_alive():
                logger.warning("Mount thread did not finish gracefully")
                if not unmount_success:
                    logger.warning("Attempting force unmount...")
                    self.force_unmount()
        
        # Cleanup FUSE driver resources
        if self.fuse_driver:
            try:
                self.fuse_driver.destroy("/")  # Trigger cleanup
            except Exception as e:
                logger.warning(f"Error during FUSE driver cleanup: {e}")
        
        logger.info("Graceful shutdown completed")
    
    def unmount_filesystem(self) -> bool:
        """Attempt to unmount the filesystem gracefully."""
        if not self.config:
            return False
            
        mountpoint = self.config.mountpoint
        logger.info(f"Attempting to unmount {mountpoint}...")
        
        # Try fusermount first (preferred for FUSE)
        for cmd in [["fusermount", "-u", mountpoint], ["fusermount3", "-u", mountpoint]]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if result.returncode == 0:
                    logger.info("✅ Filesystem unmounted successfully")
                    return True
                else:
                    logger.warning(f"Unmount failed with {' '.join(cmd)}: {result.stderr.decode()}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Unmount command {' '.join(cmd)} timed out")
            except FileNotFoundError:
                continue  # Try next command
            except Exception as e:
                logger.warning(f"Unmount error with {' '.join(cmd)}: {e}")
        
        return False
    
    def force_unmount(self) -> None:
        """Force unmount as last resort."""
        if not self.config:
            return
            
        mountpoint = self.config.mountpoint
        logger.warning(f"Attempting force unmount of {mountpoint}...")
        
        try:
            subprocess.run(["umount", "-f", mountpoint], capture_output=True, timeout=5)
        except Exception as e:
            logger.error(f"Force unmount failed: {e}")

    def run(self, config: "Config", fuse_driver: "AIDriveFUSE") -> None:
        """Main daemon run method."""
        self.config = config
        self.fuse_driver = fuse_driver
        
        # Create PID file
        self.create_pid_file(config.mountpoint)
        
        # Set up signal handlers
        self.setup_signal_handlers()
        
        # Ensure mount point directory exists
        os.makedirs(config.mountpoint, exist_ok=True)
        
        # Start FUSE mount in separate thread
        self.mount_thread = threading.Thread(
            target=self.mount_async,
            args=(config, fuse_driver),
            daemon=False,
            name="FUSEMountThread"
        )
        
        logger.info("🔧 Starting daemon with threaded mount...")
        self.mount_thread.start()

        # Wait for mount to initialize
        logger.info("⏳ Waiting for mount to initialize...")
        mount_succeeded = self.wait_for_mount(config.mountpoint)

        if mount_succeeded:
            logger.info(f"✅ AI Drive mounted successfully at {config.mountpoint}")
            logger.info("✅ Mount daemon running in background")
            logger.info("📌 Daemon started. Use Ctrl+C to stop or unmount to terminate.")

            # Keep process alive and monitor mount status
            self.monitor_mount()
        else:
            logger.error("❌ Mount failed - filesystem not accessible")
            sys.exit(1)

    def wait_for_mount(self, mountpoint: str, max_attempts: int = 20) -> bool:
        """Wait for mount to be ready with retry logic."""
        for attempt in range(max_attempts):
            try:
                mount_check_result = subprocess.run(
                    ["mountpoint", "-q", mountpoint],
                    capture_output=True,
                    timeout=5
                )
                if mount_check_result.returncode == 0:
                    return True
            except subprocess.TimeoutExpired:
                logger.warning(f"Mount check timed out (attempt {attempt + 1}/{max_attempts})")
            except Exception as e:
                logger.debug(f"Mount check failed: {e}")

            # Check if mount thread is still alive
            if self.mount_thread and not self.mount_thread.is_alive():
                logger.error("❌ Mount thread died unexpectedly")
                return False

            time.sleep(0.5)

            # Show progress every 5 attempts
            if (attempt + 1) % 5 == 0:
                logger.info(f"⏳ Still waiting... ({attempt + 1}/{max_attempts} attempts)")

        return False

    def monitor_mount(self) -> None:
        """Monitor mount status and keep daemon alive."""
        while not self.stop_event.is_set():
            time.sleep(2)  # Check every 2 seconds
            
            # Check if still mounted
            if self.config:
                try:
                    mount_check = subprocess.run(
                        ["mountpoint", "-q", self.config.mountpoint],
                        capture_output=True,
                        timeout=5
                    )
                    if mount_check.returncode != 0:
                        logger.warning("⚠️ Filesystem unmounted externally, exiting...")
                        self.stop_event.set()
                        break
                except Exception as e:
                    logger.debug(f"Mount check error: {e}")

        # Cleanup when monitoring stops
        self.cleanup_after_monitoring()

    def cleanup_after_monitoring(self) -> None:
        """Cleanup after monitoring loop ends."""
        logger.info("⏳ Waiting for mount thread to finish...")
        
        if self.mount_thread:
            self.mount_thread.join(timeout=15)
            
            if self.mount_thread.is_alive():
                logger.warning("⚠️ Mount thread still alive after timeout")
                if self.config:
                    try:
                        check = subprocess.run(
                            ["mountpoint", "-q", self.config.mountpoint],
                            capture_output=True, timeout=2
                        )
                        if check.returncode == 0:
                            logger.error("❌ Filesystem still mounted, manual intervention may be required")
                            logger.error(f"Run: sudo fusermount -u {self.config.mountpoint}")
                        else:
                            logger.info("✅ Filesystem unmounted, thread will terminate")
                    except Exception:
                        pass
            else:
                logger.info("✅ Mount thread terminated cleanly")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Drive FUSE daemon - Enhanced version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic daemon start
  python3 mount_daemon.py /mnt/aidrive
  
  # With custom cache and debug
  python3 mount_daemon.py /mnt/aidrive --cache-location=/var/cache/aidrive --debug
  
  # Check if already running
  ps aux | grep mount_daemon
        """
    )
    parser.add_argument("mountpoint", nargs="?", default="/mnt/aidrive",
                        help="Mount point directory (default: /mnt/aidrive)")
    parser.add_argument("--cache-location", default="/tmp/aidrive_cache",
                        help="Cache directory location (default: /tmp/aidrive_cache)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")
    parser.add_argument("--pid-file", 
                        help="Custom PID file location (auto-generated if not specified)")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        default="INFO", help="Set logging level")

    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    daemon = MountDaemon()
    
    logger.info("🚀 Starting AI Drive FUSE daemon...")

    try:
        from aidrive_fuse.fuse_driver import AIDriveFUSE
        from aidrive_fuse.config import Config

        # Create config with user-specified or default values
        config = Config(
            cache_location=args.cache_location,
            mountpoint=args.mountpoint,
            foreground=True,  # Always foreground in daemon mode
            debug=args.debug
        )

        # Ensure cache directory exists
        os.makedirs(config.cache_location, exist_ok=True)
        logger.info(f"✅ Cache directory: {config.cache_location}")
        logger.info(f"✅ Mount point: {config.mountpoint}")

        # Create FUSE driver
        fuse_driver = AIDriveFUSE(config)
        logger.info("✅ FUSE driver created")

        # Test API connection
        try:
            if fuse_driver.client:
                files = fuse_driver.client.list_files("/")
                if files and files.items:
                    logger.info(f"✅ API connected! Found {len(files.items)} items")
                else:
                    logger.info("✅ API connected! (Mock mode)")
            else:
                logger.warning("⚠️ No client available")
        except Exception as e:
            logger.warning(f"⚠️ API test: {e}")

        # Run the daemon
        daemon.run(config, fuse_driver)

    except KeyboardInterrupt:
        logger.info("\n🛑 Mount daemon interrupted")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Mount failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
