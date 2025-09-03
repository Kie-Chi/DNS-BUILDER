import argparse
import logging
from .config import Config
from .builder.build import Builder
from .utils.logger import setup_logger
from .exceptions import DNSBuilderError, ConfigError
import traceback

def main():
    parser = argparse.ArgumentParser(description="DNS Builder CLI")
    parser.add_argument("config_file", help="Path to the config.yml file.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "-g", "--graph", 
        help="Generate a DOT file for the network topology graph and save it to the specified path."
    )
    args = parser.parse_args()

    setup_logger(debug=args.debug)
    
    try:
        config = Config(args.config_file)
        builder = Builder(config, graph_output=args.graph)
        builder.run()
    except ConfigError as e:
        logging.error(f"A configuration error occurred: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except DNSBuilderError as e:
        logging.error(f"A build error occurred: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except FileNotFoundError as e:
        logging.error(f"A required file was not found: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()