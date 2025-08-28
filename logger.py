# logger.py
import logging
import sys
import os

try:
    import colorlog
except ImportError:
    # If colorlog is not installed, we'll use a basic fallback
    colorlog = None

def setup_logger(debug: bool = False):
    """
    Configures the root logger for the application with colored output.
    """
    logger = logging.getLogger()
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    # Prevent duplicate handlers if this function is called multiple times
    if logger.handlers:
        return

    # Check if we should use colors
    # Respect NO_COLOR env var (https://no-color.org/)
    use_colors = sys.stdout.isatty() and colorlog and not os.environ.get("NO_COLOR")

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if use_colors:
        # Define the format with color codes
        formatter = colorlog.ColoredFormatter(
            '%(log_color)s[%(levelname).4s]%(reset)s %(message)s',
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
        formatter = logging.Formatter('[%(levelname).4s] %(message)s')

    handler.setFormatter(formatter)
    logger.addHandler(handler)