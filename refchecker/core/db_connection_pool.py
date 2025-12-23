"""
Thread-safe database connection pool for parallel reference checking.

This module provides a connection pool that allows multiple worker threads
to safely access SQLite databases in parallel by maintaining per-thread connections.
"""

import threading
import sqlite3
import logging
from typing import Dict, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseConnectionPool:
    """
    Thread-safe SQLite connection pool.
    
    Each thread gets its own database connection to avoid SQLite's
    "objects created in a thread can only be used in that same thread" restriction.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize the connection pool.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._connections: Dict[int, sqlite3.Connection] = {}
        self._lock = threading.Lock()
    
    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection for the current thread.
        
        Returns:
            SQLite connection object for the current thread
        """
        thread_id = threading.get_ident()
        
        with self._lock:
            if thread_id not in self._connections:
                logger.debug(f"Creating new database connection for thread {thread_id}")
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row  # Return rows as dictionaries
                self._connections[thread_id] = conn
            
            return self._connections[thread_id]
    
    @contextmanager
    def connection(self):
        """
        Context manager for database connections.
        
        Usage:
            with pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")
        """
        conn = self.get_connection()
        try:
            yield conn
        except Exception:
            # Rollback on error
            conn.rollback()
            raise
        else:
            # Commit on success
            conn.commit()
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            # Don't try to close connections from different threads - SQLite doesn't allow it
            # The connections will be cleaned up when the worker threads exit
            logger.debug(f"Clearing connection pool (connections will close when threads exit)")
            self._connections.clear()
    
    def close_current_thread(self):
        """Close the connection for the current thread."""
        thread_id = threading.get_ident()
        
        with self._lock:
            if thread_id in self._connections:
                try:
                    self._connections[thread_id].close()
                    del self._connections[thread_id]
                    logger.debug(f"Closed database connection for current thread {thread_id}")
                except Exception as e:
                    logger.error(f"Error closing connection for thread {thread_id}: {e}")


class ThreadSafeLocalChecker:
    """
    Thread-safe wrapper for LocalNonArxivReferenceChecker that uses connection pooling.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize the thread-safe checker.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.connection_pool = DatabaseConnectionPool(db_path)
    
    def verify_reference(self, reference):
        """
        Thread-safe reference verification.
        
        Args:
            reference: Reference dictionary to verify
            
        Returns:
            Tuple of (verified_data, errors, paper_url)
        """
        # Import here to avoid circular imports
        from checkers.local_semantic_scholar import LocalNonArxivReferenceChecker
        
        # Get thread-local connection
        conn = self.connection_pool.get_connection()
        
        # Create a properly initialized checker instance with thread-local connection
        checker = LocalNonArxivReferenceChecker.__new__(LocalNonArxivReferenceChecker)
        
        # Initialize the essential attributes (same as __init__ does)
        checker.db_path = self.db_path
        checker.conn = conn
        # The connection should already have row_factory set from the pool
        
        # Call the verification method
        return checker.verify_reference(reference)
    
    def close(self):
        """Close all database connections."""
        self.connection_pool.close_all()