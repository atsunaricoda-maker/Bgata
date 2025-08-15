#!/usr/bin/env python3
"""
AI Drive FUSE daemon script - always runs asynchronously
"""
import os
import sys
import argparse
import threading
import time
import signal
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidrive_fuse.config import Config
    from aidrive_fuse.fuse_driver import AIDriveFUSE


def mount_async(config: "Config", fuse_driver: "AIDriveFUSE", stop_event: threading.Event) -> None:
    """Run FUSE mount in a separate thread to avoid blocking"""
    try:
        from fuse import FUSE  # type: ignore

        print("🔧 Starting FUSE mount...")

        # This will block in the thread
        FUSE(fuse_driver, config.mountpoint,
             foreground=True,  # Always foreground in daemon mode
             debug=config.debug,
             allow_other=True)

    except Exception as e:
        print(f"❌ FUSE mount failed in thread: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Signal that the mount has stopped
        stop_event.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Drive FUSE daemon")
    parser.add_argument("mountpoint", nargs="?", default="/mnt/aidrive",
                        help="Mount point directory (default: /mnt/aidrive)")
    parser.add_argument("--cache-location", default="/tmp/aidrive_cache",
                        help="Cache directory location (default: /tmp/aidrive_cache)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")

    args = parser.parse_args()

    print("🚀 Starting AI Drive FUSE daemon...")

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

        os.makedirs(config.cache_location, exist_ok=True)
        print(f"✅ Cache directory: {config.cache_location}")
        print(f"✅ Mount point: {config.mountpoint}")

        # Create FUSE driver
        fuse_driver = AIDriveFUSE(config)
        print("✅ FUSE driver created")

        # Test API connection
        try:
            if fuse_driver.client:
                files = fuse_driver.client.list_files("/")
                if files and files.items:
                    print(f"✅ API connected! Found {len(files.items)} items")
                else:
                    print("✅ API connected! (Mock mode)")
            else:
                print("⚠️ No client available")
        except Exception as e:
            print(f"⚠️ API test: {e}")

        # Always run in daemon mode with threading
        print("🔧 Starting daemon with threaded mount...")

        # Create a stop event for graceful shutdown
        stop_event = threading.Event()
        
        # Initialize mount thread reference for signal handler
        current_mount_thread = None
        
        # Set up signal handler for graceful shutdown
        def signal_handler(signum: int, frame: object) -> None:
            print("\n🛑 Received stop signal, cleaning up...")
            # Try to unmount gracefully
            unmount_success = False
            try:
                result = subprocess.run(["fusermount", "-u", config.mountpoint],
                                        capture_output=True, timeout=10)
                if result.returncode == 0:
                    unmount_success = True
                    print("✅ Filesystem unmounted successfully")
                else:
                    print(f"⚠️ Unmount failed with code {result.returncode}: {result.stderr.decode()}")
            except subprocess.TimeoutExpired:
                print("⚠️ Unmount command timed out")
            except Exception as e:
                print(f"⚠️ Failed to unmount: {e}")

            # Set stop event to signal the mount thread
            stop_event.set()

            # If unmount failed and thread exists, try force killing
            if not unmount_success and current_mount_thread and current_mount_thread.is_alive():
                print("⚠️ Attempting forceful termination...")
                # Try umount as alternative
                try:
                    subprocess.run(["umount", "-f", config.mountpoint],
                                   capture_output=True, timeout=5)
                except:
                    pass
            
            # Don't call sys.exit() here - let the main thread handle cleanup
            # This allows proper thread joining and cleanup

        # Start FUSE in a regular thread (not daemon)
        mount_thread = threading.Thread(
            target=mount_async,
            args=(config, fuse_driver, stop_event),
            daemon=False  # Not a daemon thread for proper cleanup
        )
        current_mount_thread = mount_thread
        
        # Register signal handlers AFTER setting current_mount_thread to avoid race condition
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        mount_thread.start()

        # Wait for mount to initialize with retry logic
        print("⏳ Waiting for mount to initialize...")

        max_attempts = 20  # 20 attempts with 0.5s delay = 10 seconds total
        mount_succeeded = False

        for attempt in range(max_attempts):
            try:
                mount_check_result = subprocess.run(
                    ["mountpoint", "-q", config.mountpoint],
                    capture_output=True,
                    timeout=5
                )
                if mount_check_result.returncode == 0:
                    mount_succeeded = True
                    break
            except subprocess.TimeoutExpired:
                print(f"⚠️ Mount check timed out (attempt {attempt + 1}/{max_attempts})")
            except Exception as e:
                print(f"⚠️ Mount check failed: {e}")
                # Continue trying even if mountpoint command has issues

            # Check if mount thread is still alive
            if not mount_thread.is_alive():
                print("❌ Mount thread died unexpectedly")
                break

            time.sleep(0.5)

            # Show progress
            if (attempt + 1) % 5 == 0:
                print(f"⏳ Still waiting... ({attempt + 1}/{max_attempts} attempts)")

        if mount_succeeded:
            print(f"✅ AI Drive mounted successfully at {config.mountpoint}")
            print("✅ Mount daemon running in background")

            # Keep the main thread alive
            print("📌 Daemon started. Use Ctrl+C to stop or unmount to terminate.")

            # Keep process alive
            while not stop_event.is_set():
                time.sleep(1)
                # Check if still mounted
                try:
                    mount_check = subprocess.run(
                        ["mountpoint", "-q", config.mountpoint],
                        capture_output=True,
                        timeout=5
                    )
                    if mount_check.returncode != 0:
                        print("⚠️ Filesystem unmounted, exiting...")
                        stop_event.set()
                        break
                except Exception as e:
                    # Don't exit on mountpoint check errors
                    print(f"⚠️ Mount check error: {e}")

            # Wait for mount thread to finish
            print("⏳ Waiting for mount thread to finish...")
            mount_thread.join(timeout=15)  # Give more time for cleanup

            if mount_thread.is_alive():
                print("⚠️ Mount thread still alive after timeout")
                # Last resort: check if filesystem is still mounted
                try:
                    check = subprocess.run(["mountpoint", "-q", config.mountpoint],
                                           capture_output=True, timeout=2)
                    if check.returncode == 0:
                        print("❌ Filesystem still mounted, manual intervention required")
                        print(f"Run: sudo fusermount -u {config.mountpoint}")
                    else:
                        print("✅ Filesystem unmounted, thread will terminate")
                except Exception:
                    pass
            else:
                print("✅ Mount thread terminated cleanly")

        else:
            print("❌ Mount failed - filesystem not accessible")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 Mount daemon interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Mount failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
