# logger.py
import logging
import sys
import os

try:
    import colorlog
except ImportError:
    # If colorlog is not installed, we'll use a basic fallback
    colorlog = None
    
from .. import constants


def setup_logger(debug: bool = False, module_levels: dict | None = None, log_file: str | None = None):
    """
    Configures the root logger for the application with colored output.
    
    Args:
        debug: Enable debug logging level
        module_levels: Per-module log levels
        log_file: Optional path to log file. If provided, logs will be written to this file.
    """
    logger = logging.getLogger()
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    # Prevent duplicate handlers if this function is called multiple times
    if logger.handlers:
        # Even if handlers exist, still allow adjusting module levels dynamically
        _apply_module_levels(module_levels)
        return

    # Check if we should use colors
    # Respect NO_COLOR env var (https://no-color.org/)
    use_colors = sys.stdout.isatty() and colorlog and not os.environ.get("NO_COLOR")

    # Console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.NOTSET)

    if use_colors:
        # Define the format with color codes
        console_formatter = colorlog.ColoredFormatter(
            '%(log_color)s[%(levelname).4s]%(reset)s %(cyan)s%(name)s%(reset)s: %(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            },
            reset=True,
            style='%'
        )
    else:
        # Basic formatter for non-color environments
        console_formatter = logging.Formatter('[%(levelname).4s] %(name)s: %(message)s')

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler (if log_file is specified)
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
            file_handler.setLevel(logging.NOTSET)
            # File logs don't need colors, use detailed format
            file_formatter = logging.Formatter(
                '%(asctime)s [%(levelname).4s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            logging.info(f"Logging to file: {log_file}")
        except Exception as e:
            logging.error(f"Failed to create log file handler for '{log_file}': {e}")

    # Apply per-module levels from env or argument
    _apply_module_levels(module_levels)


def _apply_module_levels(module_levels: dict | None):
    """Apply per-module logger levels from mapping or env var DNSB_LOG_LEVELS.

    module_levels format: {"dnsbuilder.builder.substitute": "DEBUG", "dnsbuilder.builder.resolve": "INFO"}
    Env var example: DNSB_LOG_LEVELS="dnsbuilder.builder.substitute=DEBUG,dnsbuilder.builder.resolve=INFO"
    """
    # Parse from env if not provided
    if module_levels is None:
        env = os.environ.get("DNSB_LOG_LEVELS")
        if env:
            module_levels = {}
            for pair in env.split(','):
                pair = pair.strip()
                if not pair:
                    continue
                if '=' not in pair:
                    continue
                name, lvl = pair.split('=', 1)
                module_levels[name.strip()] = lvl.strip().upper()

    if not module_levels:
        return

    for name, lvl_str in module_levels.items():
        try:
            norm_name = _normalize_module_name(name)
            lvl = getattr(logging, lvl_str.upper())
            logging.getLogger(norm_name).setLevel(lvl)
        except Exception:
            # Silently ignore invalid levels to avoid crashing
            continue


def _normalize_module_name(name: str) -> str:
    """Normalize provided module name with alias and auto-prefix.

    - If name is an alias, expand to full module path.
    - If name ends with '.*', treat it as base logger (strip the wildcard).
    - If name does not start with 'dnsbuilder.' and begins with a known top module, prefix 'dnsbuilder.'.
    """
    # Alias expansion
    if name in constants.LOG_ALIAS_MAP:
        return constants.LOG_ALIAS_MAP[name]
    # Wildcard base (e.g., 'builder.*' => 'dnsbuilder.builder')
    if name.endswith('.*'):
        name = name[:-2]
    # Auto-prefix for our modules
    if not name.startswith('dnsbuilder.'):
        first = name.split('.', 1)[0]
        if first in constants.KNOWN_TOP_MODULES:
            name = f'dnsbuilder.{name}'
    return name