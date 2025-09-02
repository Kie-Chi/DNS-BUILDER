# main.py
import sys
import os
import logging
from argparse import ArgumentParser, Namespace
from src.config.config import Config
from src.build.build import Builder
import traceback
from src.log.logger import setup_logger # Import the setup function


def parse_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument(
        "-c", "--config", type=str, required=True, help="config file path"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="if set, log verbose"
    )
    return parser.parse_args()

def main():
    """Main function to run the DNS builder."""
    args = parse_args()
    config_file = args.config
    is_debug_mode = True if args.verbose else False
    setup_logger(debug=is_debug_mode)
    logger = logging.getLogger(__name__)
    logger.info(f"Reading configuration from {config_file}...")
    try:
        config = Config(config_file)
        builder = Builder(config)
        builder.run()
    except Exception as e:
        # Use the logger to report errors
        logger.critical(f"Build failed due to an error: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()