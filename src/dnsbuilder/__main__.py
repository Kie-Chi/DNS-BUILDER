import argparse
import logging
from .config import Config
from .builder.build import Builder
from .builder.cached_builder import CachedBuilder
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
import asyncio


async def main():
    parser = argparse.ArgumentParser(description="DNS Builder CLI")
    parser.add_argument("config_file", nargs='?', default=None, help="Path to the config.yml file.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "-l",
        "--log-levels",
        help=(
            "Comma-separated per-module log levels. Examples: \n"
            "  'sub=DEBUG,res=INFO' (use aliases: sub, res, svc, bld, io, fs, conf, api, pre)\n"
            "  'builder.*=INFO' (apply to base logger)\n"
            "Overrides DNSB_LOG_LEVELS env if provided."
        ),
    )
    parser.add_argument("--vfs", action="store_true", help="Enable virtual file system.")
    parser.add_argument(
        "-g",
        "--graph",
        help="Generate a DOT file for the network topology graph and save it to the specified path.",
    )
    parser.add_argument("--ui", action="store_true", help="Start the web UI.")
    parser.add_argument(
        "-i",
        "--incremental",
        action="store_true",
        help="Enable incremental build using cache to speed up builds by only rebuilding changed services."
    )
    parser.add_argument(
        "-w",
        "--workdir",
        help=(
            "Working directory for resolving relative paths. "
            "Use '@config' to use the config file's directory, "
            "or specify an absolute/relative path. "
            "Default: current working directory."
        ),
        default=None
    )
    parser.add_argument(
        "--log-file",
        "-f",
        help="Path to log file. If specified, logs will be written to this file in addition to stderr.",
        default=None
    )
    args = parser.parse_args()

    module_levels = None
    if args.log_levels:
        module_levels = {}
        for pair in args.log_levels.split(','):
            pair = pair.strip()
            if not pair or '=' not in pair:
                continue
            name, lvl = pair.split('=', 1)
            module_levels[name.strip()] = lvl.strip().upper()

    setup_logger(debug=args.debug, module_levels=module_levels, log_file=args.log_file)

    if args.ui:
        uvicorn.run(app, host="0.0.0.0", port=8000)
        return

    if not args.config_file:
        parser.error("the following arguments are required: config_file")

    from pathlib import Path
    from .io.path import DNSBPath
    
    config_path = Path(args.config_file).resolve()
    config_file_abs = str(config_path)
    
    workdir = None
    if args.workdir == "@config":
        workdir = DNSBPath(config_path.parent)
        logging.info(f"Using config directory as workdir: {workdir}")
    elif args.workdir:
        workdir_path = Path(args.workdir).resolve()
        workdir = DNSBPath(workdir_path)
        logging.info(f"Using custom workdir: {workdir}")
    else:
        workdir = DNSBPath(Path.cwd())
        logging.debug(f"Using default workdir (cwd): {workdir}")

    try:
        cli_fs = create_app_fs(use_vfs=args.vfs, chroot=workdir)
        config = Config(config_file_abs, cli_fs)
        
        # Choose builder based on incremental flag
        if args.incremental:
            builder = CachedBuilder(config, graph_output=args.graph, fs=cli_fs)
            logging.info("Using incremental build with cache")
        else:
            builder = Builder(config, graph_output=args.graph, fs=cli_fs)
            logging.info("Using standard build")
            
        await builder.run()
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

def _sync():
    asyncio.run(main())

if __name__ == "__main__":
    _sync()
