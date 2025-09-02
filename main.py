# main.py
import sys
import os
import logging
from config import Config
from build import Builder
import traceback
from logger import setup_logger # Import the setup function

def main():
    """Main function to run the DNS builder."""
    
    is_debug_mode = os.getenv("DNSBUILDER_DEBUG", "0").lower() in ("1", "true", "yes")
    setup_logger(debug=is_debug_mode)
    
    # Get a logger for this module
    logger = logging.getLogger(__name__)

    # config_file = 'kaminsky.yml'
    config_file = "unbound_test.yml"
    
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