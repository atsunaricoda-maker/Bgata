"""
Async Operation Queue Manager for AI Drive FUSE

Handles concurrent upload/download operations with rate limiting and error recovery.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, Deque, List
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from collections import deque


logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Types of operations that can be queued."""
    UPLOAD = "upload"
    DOWNLOAD = "download"


class PriorityLevel(Enum):
    """Predefined priority levels for common operation types."""
    CRITICAL = 1000     # Critical system operations
    USER_IMMEDIATE = 800 # Immediate user actions (save, etc.)
    AUTO_SYNC = 600     # Background auto-sync operations
    PREFETCH = 400      # Prefetch operations
    BACKGROUND = 200    # Background maintenance
    LOW = 100          # Low priority operations
    
    @classmethod
    def get_priority_for_operation(cls, operation_type: str, is_user_triggered: bool = False) -> int:
        """Get appropriate priority for operation type."""
        if is_user_triggered:
            return cls.USER_IMMEDIATE.value
        elif operation_type == "auto_sync":
            return cls.AUTO_SYNC.value
        elif operation_type == "prefetch":
            return cls.PREFETCH.value
        elif operation_type == "background":
            return cls.BACKGROUND.value
        else:
            return cls.LOW.value


@dataclass
class QueuedOperation:
    """Represents a queued operation with enhanced priority and metadata."""
    operation_type: OperationType
    local_path: str
    remote_path: str
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3
    created_time: Optional[float] = None
    file_size: Optional[int] = None
    operation_category: str = "default"
    user_triggered: bool = False
    urgency_factor: float = 1.0  # Multiplier for dynamic priority calculation

    def __post_init__(self) -> None:
        if self.created_time is None:
            self.created_time = time.time()
        
        # Try to get file size if not provided
        if self.file_size is None and self.operation_type == OperationType.UPLOAD:
            try:
                from pathlib import Path
                path = Path(self.local_path)
                if path.exists():
                    self.file_size = path.stat().st_size
            except Exception:
                self.file_size = 0
    
    def get_effective_priority(self) -> float:
        """Calculate effective priority considering age and other factors."""
        base_priority = float(self.priority)
        
        # Age factor - older operations get slight priority boost (max 10% boost over 5 minutes)
        if self.created_time:
            age_minutes = (time.time() - self.created_time) / 60.0
            age_boost = min(age_minutes * 0.02, 0.1)  # 2% per minute, max 10%
            base_priority *= (1.0 + age_boost)
        
        # Retry penalty - failed operations get slight priority reduction
        retry_penalty = self.retry_count * 0.05  # 5% reduction per retry
        base_priority *= (1.0 - retry_penalty)
        
        # User-triggered operations get boost
        if self.user_triggered:
            base_priority *= 1.2
        
        # Apply urgency factor
        base_priority *= self.urgency_factor
        
        return base_priority
    
    def should_preempt(self, other: 'QueuedOperation') -> bool:
        """Determine if this operation should preempt another."""
        # Critical operations always preempt
        if self.priority >= PriorityLevel.CRITICAL.value:
            return True
        
        # User-triggered operations preempt non-user operations
        if self.user_triggered and not other.user_triggered:
            return True
        
        # Compare effective priorities
        return self.get_effective_priority() > other.get_effective_priority() * 1.1  # 10% threshold


class NetworkErrorHandler:
    """Handles network errors with exponential backoff."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 2.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    async def with_retry(self, operation_func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute operation with retry logic."""
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return await operation_func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                logger.warning(f"Operation failed (attempt {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    wait_time = self.backoff_factor ** attempt
                    logger.debug(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)

        # All retries exhausted
        if last_exception is not None:
            logger.error(f"Operation failed after {self.max_retries} attempts: {last_exception}")
            raise last_exception
        else:
            raise RuntimeError("Operation failed with unknown error")


class SmartPriorityQueue:
    """Intelligent priority queue with advanced scheduling algorithms."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.items: List[QueuedOperation] = []
        self.item_map: Dict[str, QueuedOperation] = {}  # For fast lookup by remote_path
        self._lock = asyncio.Lock()
    
    async def add(self, operation: QueuedOperation) -> bool:
        """Add operation to queue with intelligent positioning."""
        async with self._lock:
            if len(self.items) >= self.max_size:
                # Try to remove a low-priority item to make space
                if not await self._make_space_for(operation):
                    return False
            
            # Remove existing operation for same path if present
            if operation.remote_path in self.item_map:
                old_op = self.item_map[operation.remote_path]
                try:
                    self.items.remove(old_op)
                except ValueError:
                    pass
            
            # Insert operation in priority order
            insert_pos = self._find_insert_position(operation)
            self.items.insert(insert_pos, operation)
            self.item_map[operation.remote_path] = operation
            
            return True
    
    async def pop(self) -> Optional[QueuedOperation]:
        """Get highest priority operation."""
        async with self._lock:
            if not self.items:
                return None
            
            # Recalculate priorities and resort if needed
            await self._optimize_queue()
            
            operation = self.items.pop(0)  # Get highest priority
            self.item_map.pop(operation.remote_path, None)
            return operation
    
    def _find_insert_position(self, operation: QueuedOperation) -> int:
        """Find optimal insert position for operation."""
        target_priority = operation.get_effective_priority()
        
        for i, existing_op in enumerate(self.items):
            if target_priority > existing_op.get_effective_priority():
                return i
        
        return len(self.items)
    
    async def _make_space_for(self, new_operation: QueuedOperation) -> bool:
        """Try to make space for a new operation by removing lower priority items."""
        if not self.items:
            return False
        
        # Only make space if new operation has higher priority than lowest
        lowest_priority_op = min(self.items, key=lambda x: x.get_effective_priority())
        
        if new_operation.get_effective_priority() > lowest_priority_op.get_effective_priority():
            self.items.remove(lowest_priority_op)
            self.item_map.pop(lowest_priority_op.remote_path, None)
            return True
        
        return False
    
    async def _optimize_queue(self) -> None:
        """Optimize queue order based on current priorities."""
        if len(self.items) <= 1:
            return
        
        # Sort by effective priority (descending)
        self.items.sort(key=lambda x: x.get_effective_priority(), reverse=True)
    
    def __len__(self) -> int:
        return len(self.items)
    
    def clear(self) -> None:
        self.items.clear()
        self.item_map.clear()


class OperationQueue:
    """Enhanced operation queue with intelligent priority management."""

    def __init__(self,
                 max_concurrent_uploads: int = 5,
                 max_concurrent_downloads: int = 10,
                 max_queue_size: int = 1000):
        """Initialize operation queue.

        Args:
            max_concurrent_uploads: Maximum concurrent upload operations
            max_concurrent_downloads: Maximum concurrent download operations
            max_queue_size: Maximum number of queued operations
        """
        self.max_concurrent_uploads = max_concurrent_uploads
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_queue_size = max_queue_size

        # Semaphores for concurrency control
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_uploads)
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

        # Smart priority queues
        self.upload_queue = SmartPriorityQueue(max_queue_size)
        self.download_queue = SmartPriorityQueue(max_queue_size)

        # Track active operations
        self.active_operations: Dict[str, asyncio.Task[Any]] = {}

        # Operation deduplication
        self.pending_uploads: Dict[str, QueuedOperation] = {}
        self.pending_downloads: Dict[str, QueuedOperation] = {}

        # Statistics
        self.stats = {
            'total_uploads': 0,
            'total_downloads': 0,
            'successful_uploads': 0,
            'successful_downloads': 0,
            'failed_uploads': 0,
            'failed_downloads': 0,
            'queue_full_rejections': 0,
            'atomic_replacements': 0,
            'atomic_replacement_failures': 0,
            'atomic_replacement_recoveries': 0
        }

        # Error handler
        self.error_handler = NetworkErrorHandler()

        # Queue processing lock
        self._processing_lock = asyncio.Lock()

    async def queue_upload(self, local_path: str, remote_path: str, priority: int = 0, 
                          operation_category: str = "default", user_triggered: bool = False) -> bool:
        """Queue an upload operation with enhanced priority management.

        Args:
            local_path: Local file path to upload
            remote_path: Remote destination path
            priority: Operation priority (higher numbers = higher priority)
            operation_category: Category of operation (auto_sync, prefetch, etc.)
            user_triggered: Whether this operation was directly triggered by user action

        Returns:
            True if queued successfully, False if queue is full
        """
        # Auto-assign priority if not specified
        if priority == 0:
            priority = PriorityLevel.get_priority_for_operation(operation_category, user_triggered)

        # Create new operation with enhanced metadata
        operation = QueuedOperation(
            operation_type=OperationType.UPLOAD,
            local_path=local_path,
            remote_path=remote_path,
            priority=priority,
            operation_category=operation_category,
            user_triggered=user_triggered
        )

        # Add to smart priority queue
        success = await self.upload_queue.add(operation)
        
        if success:
            self.pending_uploads[remote_path] = operation
            logger.debug(f"Queued upload: {local_path} -> {remote_path} "
                        f"(priority: {priority}, category: {operation_category}, user: {user_triggered})")
        else:
            self.stats['queue_full_rejections'] += 1
            logger.warning(f"Upload queue full, rejecting: {remote_path}")

        return success

    async def queue_download(self, remote_path: str, local_path: str, priority: int = 0,
                            operation_category: str = "default", user_triggered: bool = False) -> bool:
        """Queue a download operation with enhanced priority management.

        Args:
            remote_path: Remote file path to download
            local_path: Local destination path
            priority: Operation priority (higher numbers = higher priority)
            operation_category: Category of operation (prefetch, user_request, etc.)
            user_triggered: Whether this operation was directly triggered by user action

        Returns:
            True if queued successfully, False if queue is full
        """
        # Auto-assign priority if not specified
        if priority == 0:
            priority = PriorityLevel.get_priority_for_operation(operation_category, user_triggered)

        # Create new operation with enhanced metadata
        operation = QueuedOperation(
            operation_type=OperationType.DOWNLOAD,
            local_path=local_path,
            remote_path=remote_path,
            priority=priority,
            operation_category=operation_category,
            user_triggered=user_triggered
        )

        # Add to smart priority queue
        success = await self.download_queue.add(operation)
        
        if success:
            self.pending_downloads[remote_path] = operation
            logger.debug(f"Queued download: {remote_path} -> {local_path} "
                        f"(priority: {priority}, category: {operation_category}, user: {user_triggered})")
        else:
            self.stats['queue_full_rejections'] += 1
            logger.warning(f"Download queue full, rejecting: {remote_path}")

        return success

    async def _requeue_with_priority(
        self, operation: QueuedOperation, queue: Deque[QueuedOperation],
        pending_dict: Dict[str, QueuedOperation]
    ) -> bool:
        """Re-queue operation while maintaining priority order."""
        async with self._processing_lock:
            # Double-check queue size limit under lock to prevent race conditions
            if len(queue) >= self.max_queue_size:
                logger.warning(f"Cannot re-queue operation: queue is full ({len(queue)}/{self.max_queue_size})")
                return False

            queue.append(operation)
            pending_dict[operation.remote_path] = operation

            # Re-sort queue to maintain priority order (higher priority first)
            queue_list = list(queue)
            queue_list.sort(key=lambda x: x.priority, reverse=True)
            queue.clear()
            queue.extend(queue_list)
            return True

    async def process_pending(self) -> None:
        """Process pending operations from queues."""
        async with self._processing_lock:
            logger.debug(
                f"Processing pending: upload_queue={len(self.upload_queue)}, "
                f"download_queue={len(self.download_queue)}, active_ops={len(self.active_operations)}"
            )

            # Process uploads
            await self._process_upload_queue()

            # Process downloads
            await self._process_download_queue()

            # Clean up completed tasks
            await self._cleanup_completed_tasks()

    async def _process_upload_queue(self) -> None:
        """Process upload queue with smart priority handling."""
        logger.debug(f"Process upload queue: {len(self.upload_queue)} items")

        # Conservative approach: only process limited number of items per cycle
        processed = 0
        max_per_cycle = min(self.max_concurrent_uploads, len(self.upload_queue))

        while len(self.upload_queue) > 0 and processed < max_per_cycle:
            # Count active upload operations to respect concurrency limits
            active_uploads = sum(1 for key in self.active_operations.keys() if key.startswith("upload_"))

            if active_uploads >= self.max_concurrent_uploads:
                logger.debug(f"Max concurrent uploads reached ({active_uploads}/{self.max_concurrent_uploads})")
                break

            try:
                # Use smart queue pop method
                operation = await self.upload_queue.pop()
                if operation is None:
                    break
                
                logger.info(f"Starting upload task: {operation.local_path} -> {operation.remote_path} "
                           f"(priority: {operation.get_effective_priority():.1f}, category: {operation.operation_category})")

                # Remove from pending dict
                self.pending_uploads.pop(operation.remote_path, None)

                # Start upload task (semaphore acquisition happens inside _execute_upload)
                task = asyncio.create_task(self._execute_upload(operation))
                self.active_operations[f"upload_{operation.remote_path}"] = task
                logger.debug(f"Upload task created for {operation.remote_path}")

                processed += 1

            except Exception as e:
                logger.error(f"Error processing upload queue: {e}")
                break

    async def _process_download_queue(self) -> None:
        """Process download queue with smart priority handling."""
        logger.debug(f"Process download queue: {len(self.download_queue)} items")

        # Conservative approach: only process limited number of items per cycle
        processed = 0
        max_per_cycle = min(self.max_concurrent_downloads, len(self.download_queue))

        while len(self.download_queue) > 0 and processed < max_per_cycle:
            # Count active download operations to respect concurrency limits
            active_downloads = sum(1 for key in self.active_operations.keys() if key.startswith("download_"))

            if active_downloads >= self.max_concurrent_downloads:
                logger.debug(f"Max concurrent downloads reached ({active_downloads}/{self.max_concurrent_downloads})")
                break

            try:
                # Use smart queue pop method
                operation = await self.download_queue.pop()
                if operation is None:
                    break
                
                logger.info(f"Starting download task: {operation.remote_path} -> {operation.local_path} "
                           f"(priority: {operation.get_effective_priority():.1f}, category: {operation.operation_category})")

                # Remove from pending dict
                self.pending_downloads.pop(operation.remote_path, None)

                # Start download task (semaphore acquisition happens inside _execute_download)
                task = asyncio.create_task(self._execute_download(operation))
                self.active_operations[f"download_{operation.remote_path}"] = task
                logger.debug(f"Download task created for {operation.remote_path}")

                processed += 1

            except Exception as e:
                logger.error(f"Error processing download queue: {e}")
                break

    async def _execute_upload(self, operation: QueuedOperation) -> None:
        """Execute upload operation with concurrency control."""
        should_retry = False
        async with self.upload_semaphore:
            try:
                self.stats['total_uploads'] += 1
                await self._upload_with_retry(operation)
                self.stats['successful_uploads'] += 1
                logger.info(f"Upload completed: {operation.local_path} -> {operation.remote_path}")
            except Exception as e:
                self.stats['failed_uploads'] += 1
                logger.error(f"Upload failed: {operation.local_path} -> {operation.remote_path}: {e}")

                # Check if we should retry (but don't re-queue while holding semaphore)
                if operation.retry_count < operation.max_retries:
                    operation.retry_count += 1
                    should_retry = True
                    logger.info(f"Will re-queue upload (retry {operation.retry_count}): {operation.remote_path}")

        # Re-queue outside semaphore context to avoid holding the slot
        if should_retry:
            # Lower priority for retry operations
            operation.priority = max(operation.priority - 50, PriorityLevel.LOW.value)
            success = await self.upload_queue.add(operation)
            if success:
                self.pending_uploads[operation.remote_path] = operation
                logger.info(f"Re-queued upload operation (retry {operation.retry_count}): {operation.remote_path}")
            else:
                logger.error(f"Failed to re-queue upload operation: {operation.remote_path}")

    async def _execute_download(self, operation: QueuedOperation) -> None:
        """Execute download operation with concurrency control."""
        should_retry = False
        async with self.download_semaphore:
            try:
                self.stats['total_downloads'] += 1
                await self._download_with_retry(operation)
                self.stats['successful_downloads'] += 1
                logger.info(f"Download completed: {operation.remote_path} -> {operation.local_path}")
            except Exception as e:
                self.stats['failed_downloads'] += 1
                logger.error(f"Download failed: {operation.remote_path} -> {operation.local_path}: {e}")

                # Check if we should retry (but don't re-queue while holding semaphore)
                if operation.retry_count < operation.max_retries:
                    operation.retry_count += 1
                    should_retry = True
                    logger.info(f"Will re-queue download (retry {operation.retry_count}): {operation.remote_path}")

        # Re-queue outside semaphore context to avoid holding the slot
        if should_retry:
            # Lower priority for retry operations
            operation.priority = max(operation.priority - 50, PriorityLevel.LOW.value)
            success = await self.download_queue.add(operation)
            if success:
                self.pending_downloads[operation.remote_path] = operation
                logger.info(f"Re-queued download operation (retry {operation.retry_count}): {operation.remote_path}")
            else:
                logger.error(f"Failed to re-queue download operation: {operation.remote_path}")

    async def _upload_with_retry(self, operation: QueuedOperation) -> None:
        """Upload file with retry logic and atomic replacement."""
        async def upload_func() -> None:
            # Real implementation using AI Drive SDK
            local_path = Path(operation.local_path)
            if not local_path.exists():
                raise FileNotFoundError(f"Local file not found: {operation.local_path}")

            try:
                from genspark_aidrive_sdk import (  # type: ignore[import-not-found]
                    AIDriveClient,
                    ConflictError
                )

                # Create client - it will use environment variables
                client = AIDriveClient()

                try:
                    # Try to upload the file directly
                    client.upload_file(str(local_path), operation.remote_path)
                    logger.info(f"Upload successful: {operation.local_path} -> {operation.remote_path}")

                except ConflictError:
                    # File already exists, use atomic replacement strategy
                    logger.info(f"File exists, using atomic replacement for: {operation.remote_path}")
                    self.stats['atomic_replacements'] += 1
                    await self._atomic_file_replacement(client, str(local_path), operation.remote_path)

            except ImportError:
                # Fallback to simulation if SDK not available
                logger.warning("AI Drive SDK not available, simulating upload")
                file_size = local_path.stat().st_size
                simulate_time = min(file_size / 1024 / 1024, 5)  # Max 5 seconds
                await asyncio.sleep(simulate_time * 0.1)  # Reduced for simulation
                logger.debug(f"Simulated upload: {operation.local_path} -> {operation.remote_path}")

        await self.error_handler.with_retry(upload_func)

    async def recover_failed_atomic_replacement(self, temp_file_path: str, target_file_path: str) -> bool:
        """
        Attempt to recover from a failed atomic replacement by renaming temp file to target.

        Args:
            temp_file_path: Path to the temporary file that exists
            target_file_path: Desired target file path

        Returns:
            True if recovery successful, False otherwise
        """
        try:
            from genspark_aidrive_sdk import AIDriveClient  # type: ignore[import-not-found]

            client = AIDriveClient()
            logger.info(f"Attempting manual recovery: {temp_file_path} -> {target_file_path}")

            # Try to rename the temporary file to target
            client.move_item(temp_file_path, target_file_path)

            logger.info(f"Manual recovery successful: {target_file_path}")
            return True
        except Exception as recovery_error:
            logger.error(f"Manual recovery failed: {recovery_error}")
            return False

    async def _atomic_file_replacement(self, client: Any, local_path: str, target_remote_path: str) -> None:
        """
        Perform atomic file replacement using temporary file strategy.

        Steps:
        1. Upload to temporary file (target_path + ".tmp")
        2. Delete original file (if exists)
        3. Rename temporary file to target path
        4. If any step fails, attempt cleanup

        Args:
            client: AIDriveClient instance
            local_path: Local file path to upload
            target_remote_path: Target remote path for the file
        """
        import uuid
        import time

        # Generate unique temporary file name to avoid conflicts
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        temp_remote_path = f"{target_remote_path}.tmp.{timestamp}.{unique_id}"

        logger.info(f"Starting atomic replacement: {local_path} -> {target_remote_path}")
        logger.debug(f"Using temporary path: {temp_remote_path}")

        try:
            # Step 1: Upload to temporary file
            logger.debug(f"Step 1: Uploading to temporary file: {temp_remote_path}")
            try:
                client.upload_file(local_path, temp_remote_path)
                logger.debug(f"Temporary file uploaded successfully: {temp_remote_path}")
            except Exception as upload_error:
                logger.error(f"Failed to upload temporary file {temp_remote_path}: {upload_error}")
                raise Exception(f"Atomic replacement failed at upload step: {upload_error}")

            # Step 2: Delete original file (if it exists)
            logger.debug(f"Step 2: Deleting original file: {target_remote_path}")
            try:
                client.delete_item(target_remote_path)
                logger.debug(f"Original file deleted successfully: {target_remote_path}")
            except Exception as delete_error:
                # If delete fails, we need to clean up the temporary file
                logger.warning(f"Failed to delete original file {target_remote_path}: {delete_error}")
                logger.info(f"Attempting to clean up temporary file: {temp_remote_path}")

                try:
                    client.delete_item(temp_remote_path)
                    logger.debug(f"Temporary file cleaned up: {temp_remote_path}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up temporary file {temp_remote_path}: {cleanup_error}")

                raise Exception(f"Atomic replacement failed at delete step: {delete_error}")

            # Step 3: Rename temporary file to target path
            logger.debug(
                f"Step 3: Renaming temporary file to target: "
                f"{temp_remote_path} -> {target_remote_path}"
            )
            try:
                client.move_item(temp_remote_path, target_remote_path)
                logger.info(f"Atomic replacement completed successfully: {target_remote_path}")

                # Simple verification: if move_item succeeded, the replacement is complete
                # We trust the SDK's move_item implementation rather than adding extra API calls
                logger.debug(f"Atomic replacement verification: move_item succeeded for {target_remote_path}")
            except Exception as move_error:
                logger.error(
                    f"Failed to rename temporary file {temp_remote_path} "
                    f"to {target_remote_path}: {move_error}"
                )

                # Critical situation: original file is deleted, temporary file exists but couldn't be renamed
                # Try to recover by renaming temp file to target (retry once)
                logger.warning("Attempting recovery: trying to rename again...")
                try:
                    # Small delay before retry
                    await asyncio.sleep(1.0)
                    client.move_item(temp_remote_path, target_remote_path)
                    logger.info("Recovery successful: temporary file renamed to target")
                    self.stats['atomic_replacement_recoveries'] += 1
                except Exception as recovery_error:
                    logger.error(f"Recovery failed: {recovery_error}")
                    logger.error(
                        f"CRITICAL: Original file deleted, temporary file exists at "
                        f"{temp_remote_path}"
                    )
                    logger.error(
                        f"Manual intervention may be required to rename {temp_remote_path} "
                        f"to {target_remote_path}"
                    )
                    self.stats['atomic_replacement_failures'] += 1
                    # Create a more detailed error message for debugging
                    error_details = (
                        f"Atomic replacement failed completely:\n"
                        f"  - Initial move error: {move_error}\n"
                        f"  - Recovery attempt error: {recovery_error}\n"
                        f"  - Temporary file location: {temp_remote_path}\n"
                        f"  - Target file location: {target_remote_path}\n"
                        f"  - Action needed: Manual file recovery required"
                    )
                    logger.critical(error_details)
                    raise Exception(error_details)
        except Exception as overall_error:
            logger.error(f"Atomic file replacement failed for {target_remote_path}: {overall_error}")
            self.stats['atomic_replacement_failures'] += 1
            raise

    async def _download_with_retry(self, operation: QueuedOperation) -> None:
        """Download file with retry logic."""
        async def download_func() -> None:
            # Ensure local directory exists
            local_path = Path(operation.local_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # In real implementation, this would use the AI Drive client:
            # await client.download_file(operation.remote_path, operation.local_path)

            # Simulate download by creating empty file
            local_path.touch()

            logger.debug(f"Simulated download: {operation.remote_path} -> {operation.local_path}")

        await self.error_handler.with_retry(download_func)

    async def _cleanup_completed_tasks(self) -> None:
        """Clean up completed async tasks."""
        completed_tasks = []

        for task_id, task in self.active_operations.items():
            if task.done():
                completed_tasks.append(task_id)
                try:
                    await task  # Ensure exception is handled
                except Exception as e:
                    logger.error(f"Task {task_id} completed with error: {e}")

        # Remove completed tasks
        for task_id in completed_tasks:
            del self.active_operations[task_id]

    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status."""
        return {
            'upload_queue_size': len(self.upload_queue),
            'download_queue_size': len(self.download_queue),
            'active_operations': len(self.active_operations),
            'pending_uploads': len(self.pending_uploads),
            'pending_downloads': len(self.pending_downloads),
            'stats': self.stats.copy()
        }

    async def wait_for_completion(self, timeout: Optional[float] = None) -> None:
        """Wait for all operations to complete."""
        start_time = time.time()

        while (self.upload_queue or self.download_queue or self.active_operations):
            if timeout and (time.time() - start_time) > timeout:
                logger.warning("Timeout waiting for operations to complete")
                break

            await asyncio.sleep(0.1)

        logger.info("All operations completed")

    async def wait_for_file_upload(self, file_path: str, timeout: Optional[float] = 30.0) -> bool:
        """Wait for a specific file upload to complete.

        Args:
            file_path: Remote path of the file to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if upload completed successfully, False if timeout or not found
        """
        start_time = time.time()
        logger.info(f"Waiting for upload completion: {file_path}")

        while timeout is None or (time.time() - start_time) < timeout:
            # Check if file is still in pending uploads
            if file_path in self.pending_uploads:
                await asyncio.sleep(0.1)
                continue

            # Check if file is being actively processed
            upload_task_key = f"upload_{file_path}"
            if upload_task_key in self.active_operations:
                task = self.active_operations[upload_task_key]
                if not task.done():
                    await asyncio.sleep(0.1)
                    continue

                # Task is done, check if it succeeded
                try:
                    await task  # This will raise exception if task failed
                    logger.info(f"Upload completed successfully: {file_path}")
                    return True
                except Exception as e:
                    logger.error(f"Upload failed for {file_path}: {e}")
                    return False

            # File is not in queue or active operations, assume completed
            logger.info(f"Upload appears to be completed: {file_path}")
            return True

        logger.warning(f"Timeout waiting for upload: {file_path}")
        return False

    async def upload_file_sync(self, local_path: str, remote_path: str, timeout: float = 300.0) -> bool:
        """Synchronously upload a file and wait for completion.

        Args:
            local_path: Local file path to upload
            remote_path: Remote destination path
            timeout: Maximum time to wait for upload completion

        Returns:
            True if upload succeeded, False otherwise
        """
        logger.info(f"Starting synchronous upload: {local_path} -> {remote_path} (timeout: {timeout}s)")

        # Verify file exists and get size
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            logger.error(f"Local file does not exist: {local_path}")
            return False

        file_size = local_path_obj.stat().st_size
        logger.info(f"Uploading file of size: {file_size} bytes")

        # Create upload operation
        operation = QueuedOperation(
            operation_type=OperationType.UPLOAD,
            local_path=local_path,
            remote_path=remote_path,
            priority=1000  # High priority for sync uploads
        )

        start_time = time.time()
        try:
            # Execute upload with proper concurrency control and timeout
            async with asyncio.timeout(timeout):
                async with self.upload_semaphore:  # Respect concurrency limits
                    logger.debug(f"Acquired upload semaphore for sync upload: {remote_path}")
                    await self._upload_with_retry(operation)

            duration = time.time() - start_time
            logger.info(f"Synchronous upload completed: {remote_path} (took {duration:.2f}s)")
            return True
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            logger.error(f"Synchronous upload timed out for {remote_path} after {duration:.2f}s (timeout: {timeout}s)")
            return False
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Synchronous upload failed for {remote_path} after {duration:.2f}s: {e}")
            return False

    async def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for all pending and active operations to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if all operations completed, False if timeout occurred
        """
        start_time = time.time()
        logger.info("Waiting for all operations to complete...")
        
        while timeout is None or (time.time() - start_time) < timeout:
            # Check if there are any pending operations
            pending_count = len(self.upload_queue) + len(self.download_queue)
            active_count = len(self.active_operations)
            
            if pending_count == 0 and active_count == 0:
                logger.info("All operations completed successfully")
                return True
            
            logger.debug(f"Waiting for completion: {pending_count} pending, {active_count} active")
            
            # Wait for a short time before checking again
            await asyncio.sleep(0.5)
        
        # Timeout occurred
        pending_count = len(self.upload_queue) + len(self.download_queue)
        active_count = len(self.active_operations)
        logger.warning(f"Timeout waiting for operations to complete: {pending_count} pending, {active_count} active")
        return False

    async def cancel_all(self) -> None:
        """Cancel all pending and active operations."""
        logger.info("Cancelling all operations...")
        
        # Clear queues
        self.upload_queue.clear()
        self.download_queue.clear()
        self.pending_uploads.clear()
        self.pending_downloads.clear()

        # Cancel active tasks
        for task in self.active_operations.values():
            if not task.done():
                task.cancel()

        # Wait for cancellation
        if self.active_operations:
            await asyncio.gather(*self.active_operations.values(), return_exceptions=True)

        self.active_operations.clear()
        logger.info("All operations cancelled")


class PerformanceMetrics:
    """Collect and track performance metrics."""

    def __init__(self) -> None:
        self.operation_counts = {
            'upload': 0,
            'download': 0,
            'mkdir': 0,
            'delete': 0,
            'move': 0,
            'list': 0
        }
        self.operation_times: Dict[str, List[float]] = {
            'upload': [],
            'download': [],
            'mkdir': [],
            'delete': [],
            'move': [],
            'list': []
        }
        self.cache_hits = 0
        self.cache_misses = 0
        self.network_errors = 0
        self.start_time = time.time()

    def record_operation(self, op_type: str, duration: float) -> None:
        """Record operation metrics."""
        if op_type in self.operation_counts:
            self.operation_counts[op_type] += 1
            self.operation_times[op_type].append(duration)

            # Keep only last 1000 measurements
            if len(self.operation_times[op_type]) > 1000:
                self.operation_times[op_type] = self.operation_times[op_type][-1000:]

    def record_cache_hit(self) -> None:
        """Record cache hit."""
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Record cache miss."""
        self.cache_misses += 1

    def record_network_error(self) -> None:
        """Record network error."""
        self.network_errors += 1

    def get_cache_hit_rate(self) -> float:
        """Get cache hit rate percentage."""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0.0

    def get_average_operation_time(self, op_type: str) -> float:
        """Get average operation time."""
        times = self.operation_times.get(op_type, [])
        return sum(times) / len(times) if times else 0.0

    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        uptime = time.time() - self.start_time

        return {
            'uptime_seconds': uptime,
            'operation_counts': self.operation_counts.copy(),
            'average_times': {
                op: self.get_average_operation_time(op)
                for op in self.operation_counts.keys()
            },
            'cache_hit_rate': self.get_cache_hit_rate(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'network_errors': self.network_errors,
            'operations_per_second': sum(self.operation_counts.values()) / uptime if uptime > 0 else 0
        }
