"""
Logging configuration for MoJoAssistant
"""
import logging
import logging.handlers
import os
from typing import Optional
from datetime import datetime

def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = ".memory/logs",
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Set up structured logging for MoJoAssistant
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Specific log file name (optional)
        log_dir: Directory for log files
        max_file_size: Maximum size of each log file in bytes
        backup_count: Number of backup log files to keep
    
    Returns:
        Configured logger instance
    """
    
    # Create log directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Set up log file name
    if log_file is None:
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = f"mojo_assistant_{timestamp}.log"
    
    log_path = os.path.join(log_dir, log_file)
    
    # Configure root logger
    logger = logging.getLogger("mojo_assistant")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s | %(name)s | %(levelname)s | %(module)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)
    
    # Console handler (only for WARNING and above by default)
    console_handler = logging.StreamHandler()
    console_level = os.getenv("MOJO_CONSOLE_LOG_LEVEL", "WARNING")
    console_handler.setLevel(getattr(logging, console_level.upper()))
    console_handler.setFormatter(simple_formatter)
    logger.addHandler(console_handler)
    
    # Log the initialization
    logger.info(f"Logging initialized - Level: {log_level}, File: {log_path}")
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(f"mojo_assistant.{name}")

def set_console_log_level(level: str) -> None:
    """
    Dynamically change console logging level
    
    Args:
        level: New logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logger = logging.getLogger("mojo_assistant")
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(getattr(logging, level.upper()))
            logger.info(f"Console log level changed to {level}")
            break

def log_memory_operation(operation: str, details: dict, logger: logging.Logger) -> None:
    """
    Log memory operations with structured data
    
    Args:
        operation: Type of operation (e.g., 'page_out', 'embed', 'search')
        details: Dictionary of operation details
        logger: Logger instance
    """
    # Format details for logging
    detail_str = " | ".join([f"{k}={v}" for k, v in details.items()])
    logger.info(f"MEMORY_OP: {operation} | {detail_str}")

def log_embedding_operation(operation: str, model: str, backend: str, duration: float, success: bool, logger: logging.Logger) -> None:
    """
    Log embedding operations with performance metrics
    
    Args:
        operation: Type of operation (e.g., 'embed_text', 'model_switch')
        model: Model name
        backend: Backend type
        duration: Operation duration in seconds
        success: Whether operation succeeded
        logger: Logger instance
    """
    status = "SUCCESS" if success else "FAILED"
    logger.info(f"EMBEDDING_OP: {operation} | model={model} | backend={backend} | duration={duration:.3f}s | status={status}")

def log_cli_command(command: str, user_input: str, success: bool, logger: logging.Logger) -> None:
    """
    Log CLI command execution
    
    Args:
        command: Command name (e.g., '/stats', '/embed')
        user_input: Full user input
        success: Whether command succeeded
        logger: Logger instance
    """
    status = "SUCCESS" if success else "FAILED"
    # Sanitize user input for logging (remove potential sensitive data)
    sanitized_input = user_input[:100] + "..." if len(user_input) > 100 else user_input
    logger.info(f"CLI_CMD: {command} | input='{sanitized_input}' | status={status}")

def log_error_with_context(error: Exception, context: dict, logger: logging.Logger) -> None:
    """
    Log errors with additional context information
    
    Args:
        error: Exception that occurred
        context: Dictionary of context information
        logger: Logger instance
    """
    context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
    logger.error(f"ERROR: {type(error).__name__}: {str(error)} | Context: {context_str}", exc_info=True)
