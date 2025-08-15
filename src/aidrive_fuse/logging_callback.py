"""
Logging Callback Handler for AI Drive FUSE

Provides automatic log uploading functionality with configurable strategies.
"""

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Dict, Any, Set, Optional, Deque, List
import aiohttp
from datetime import datetime

from .config import Config


class LoggingCallbackHandler(logging.Handler):
    """Custom logging handler that uploads logs based on configuration."""

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=config.logging_callback_buffer_size * 2)
        self._buffer_lock = threading.Lock()
        self._immediate_levels: Set[str] = set()
        self._last_flush_time = time.time()
        self._flush_task: Optional[asyncio.Task[None]] = None

        # Parse immediate levels
        if config.logging_callback_immediate_levels:
            levels = config.logging_callback_immediate_levels.upper().split(',')
            self._immediate_levels = {level.strip() for level in levels}

        # Start background flush task for buffered strategy
        if config.logging_callback_strategy == "buffered":
            self._start_flush_task()

    def _start_flush_task(self) -> None:
        """Start the background flush task."""
        def start_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._flush_task = loop.create_task(self._flush_loop())
            loop.run_until_complete(self._flush_task)

        flush_thread = threading.Thread(target=start_loop, daemon=True)
        flush_thread.start()

    async def _flush_loop(self) -> None:
        """Background loop to flush buffer periodically."""
        while True:
            try:
                await asyncio.sleep(self.config.logging_callback_flush_interval)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Use print to avoid logging loops
                print(f"LoggingCallback flush error: {e}")

    def emit(self, record: logging.LogRecord) -> None:
        """Handle a log record - main entry point for automatic triggering."""
        if not self.config.logging_callback_enabled:
            return

        if not self.config.logging_callback_endpoint_url:
            return

        try:
            # Convert log record to dictionary
            log_data = self._record_to_dict(record)

            # Determine if should send immediately
            should_send_immediately = (
                self.config.logging_callback_strategy == "immediate" or
                record.levelname in self._immediate_levels
            )

            if should_send_immediately:
                # Send immediately in background thread
                threading.Thread(
                    target=self._send_immediately_sync,
                    args=(log_data,),
                    daemon=True
                ).start()
            else:
                # Add to buffer
                with self._buffer_lock:
                    self._buffer.append(log_data)

                    # Check if buffer is full
                    if len(self._buffer) >= self.config.logging_callback_buffer_size:
                        threading.Thread(
                            target=self._flush_buffer_sync,
                            daemon=True
                        ).start()

        except Exception as e:
            # Use print to avoid logging loops
            print(f"LoggingCallback emit error: {e}")

    def _record_to_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Convert LogRecord to dictionary for JSON serialization."""
        return {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'thread_name': record.threadName,
            'process': record.process,
            'exc_info': self.format(record) if record.exc_info else None,
        }

    def _send_immediately_sync(self, log_data: Dict[str, Any]) -> None:
        """Send log data immediately (synchronous wrapper)."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_logs([log_data]))
            loop.close()
        except Exception as e:
            print(f"LoggingCallback immediate send error: {e}")

    def _flush_buffer_sync(self) -> None:
        """Flush buffer (synchronous wrapper)."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._flush_buffer())
            loop.close()
        except Exception as e:
            print(f"LoggingCallback buffer flush error: {e}")

    async def _flush_buffer(self) -> None:
        """Flush buffered logs to remote endpoint."""
        if not self._buffer:
            return

        # Get all logs from buffer
        logs_to_send = []
        with self._buffer_lock:
            logs_to_send = list(self._buffer)
            self._buffer.clear()

        if logs_to_send:
            await self._send_logs(logs_to_send)

    async def _send_logs(self, logs: List[Dict[str, Any]]) -> None:
        """Send logs to remote endpoint via HTTP POST."""
        if not logs:
            return

        payload = {
            'source': 'aidrive-fuse',
            'version': '1.1.1',
            'logs': logs,
            'sent_at': datetime.now().isoformat()
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.config.logging_callback_endpoint_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == 200:
                        print(f"Successfully sent {len(logs)} logs")
                    else:
                        print(f"Failed to send logs: HTTP {response.status}")

        except Exception as e:
            print(f"LoggingCallback send error: {e}")

    def close(self) -> None:
        """Close the handler and flush any remaining logs."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

        # Final flush
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._flush_buffer())
            loop.close()
        except Exception:
            pass

        super().close()


def setup_logging_callback(config: Config) -> None:
    """Setup logging callback handler for the root logger."""
    if not config.logging_callback_enabled:
        return

    if not config.logging_callback_endpoint_url:
        print("Warning: logging_callback enabled but no endpoint_url specified")
        return

    # Create and add the callback handler
    callback_handler = LoggingCallbackHandler(config)

    # Add to root logger so it catches all logs
    root_logger = logging.getLogger()
    root_logger.addHandler(callback_handler)

    print(f"Logging callback enabled: {config.logging_callback_endpoint_url}")
    print(f"Strategy: {config.logging_callback_strategy}")
    print(f"Immediate levels: {config.logging_callback_immediate_levels}")
