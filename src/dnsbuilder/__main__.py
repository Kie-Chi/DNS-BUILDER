import argparse
import logging
from .config import Config
from .builder.build import Builder
from .utils.logger import setup_logger
from .io.fs import create_app_fs
from .exceptions import (
    DNSBuilderError,
    ConfigurationError,
    DefinitionError,
    BuildError,
)
import traceback
import uvicorn
from .api.main import app

def main():
    parser = argparse.ArgumentParser(description="DNS Builder CLI")
    parser.add_argument("config_file", nargs='?', default=None, help="Path to the config.yml file.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument("--vfs", action="store_true", help="Enable virtual file system.")
    parser.add_argument(
        "-g",
        "--graph",
        help="Generate a DOT file for the network topology graph and save it to the specified path.",
    )
    parser.add_argument("--ui", action="store_true", help="Start the web UI.")
    args = parser.parse_args()

    setup_logger(debug=args.debug)

    if args.ui:
        uvicorn.run(app, host="0.0.0.0", port=8000)
        return

    if not args.config_file:
        parser.error("the following arguments are required: config_file")

    try:
        cli_fs = create_app_fs(use_vfs=args.vfs)
        config = Config(args.config_file, cli_fs)
        builder = Builder(config, graph_output=args.graph, fs=cli_fs)
        builder.run()
    except ConfigurationError as e:
        logging.error(f"Configuration error: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except DefinitionError as e:
        logging.error(f"Definition error: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except BuildError as e:
        logging.error(f"Build error: {e}")
        if args.debug:
            traceback.print_exc()
        exit(1)
    except DNSBuilderError as e:
        logging.error(f"An unexpected application error occurred: {e}")
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