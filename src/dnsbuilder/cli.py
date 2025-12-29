import click
import logging
import traceback
import asyncio
import uvicorn
import yaml
from python_on_whales import DockerClient, docker
from pathlib import Path as StdPath

from .config import Config
from .builder import Builder, CachedBuilder
from .utils import setup_logger
from .io import create_app_fs, DNSBPath, Path
from .exceptions import (
    DNSBuilderError,
    ConfigurationError,
    DefinitionError,
    BuildError,
)
from .api.main import app
from . import __version__

def complete_config_files(ctx, param, incomplete):
    """Auto-complete .yml and .yaml config files in current directory"""
    try:
        cwd = StdPath.cwd()
        # Find all yml/yaml files
        yml_files = list(cwd.glob('*.yml')) + list(cwd.glob('*.yaml'))
        
        # Get relative paths and filter by incomplete input
        file_names = [
            f.name for f in yml_files
            if f.name.startswith(incomplete)
        ]
        
        return sorted(file_names)
    except Exception as e:
        logging.debug(f"Config file auto-completion failed: {e}")
        return []

def complete_services(ctx, param, incomplete):
    """Auto-complete service names from docker-compose.yml"""
    config_file = ctx.params.get('config_file')
    if not config_file:
        return []
    
    try:
        # Get absolute path and workdir
        config_path = StdPath(config_file)
        if not config_path.is_absolute():
            config_path = config_path.resolve()
        
        if not config_path.exists():
            return []
        
        # Parse config file to get project name directly
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        project_name = config_data.get('name')
        if not project_name:
            return []
        
        # Determine workdir (prefer from context params, fallback to config parent)
        workdir = ctx.params.get('workdir')
        if workdir:
            if workdir == "@config":
                workdir = config_path.parent
            elif workdir == "@cwd":
                workdir = StdPath.cwd()
            else:
                workdir = StdPath(workdir).resolve()
        else:
            workdir = config_path.parent
        
        # Find docker-compose.yml
        output_dir = workdir / "output" / project_name
        compose_file = output_dir / "docker-compose.yml"
        
        if not compose_file.exists():
            return []
        
        # Parse docker-compose.yml to get all services
        with open(compose_file, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        services = compose_data.get('services', {})
        
        # Filter services that match incomplete input
        # Exclude builder services (they shouldn't be interacted with)
        service_names = [
            name for name in sorted(services.keys())
            if not name.startswith('dnsb-image-builder-') and name.startswith(incomplete)
        ]
        
        return service_names
        
    except Exception as e:
        # Silently fail for auto-completion
        logging.debug(f"Auto-completion failed: {e}")
        return []


def get_paths(config_file: str, workdir: str = None):
    """Get absolute config path and workdir"""
    dnsb_path = DNSBPath(config_file)
    if dnsb_path.is_absolute():
        abs_cfg = str(dnsb_path)
    else:
        dnsb_path = DNSBPath(Path(config_file).resolve())
        abs_cfg = str(dnsb_path)
    
    if workdir == "@config":
        workdir = dnsb_path.parent if dnsb_path.protocol == "file" else DNSBPath(Path.cwd())
        logging.info(f"Using config directory as workdir: {workdir}")
    elif workdir:
        workdir_path = Path(workdir).resolve()
        workdir = DNSBPath(workdir_path)
        logging.info(f"Using custom workdir: {workdir}")
    elif workdir == "@cwd":
        workdir = DNSBPath(Path.cwd())
        logging.info(f"Using current working directory as workdir: {workdir}")
    else:
        workdir = dnsb_path.parent if dnsb_path.protocol == "file" else DNSBPath(Path.cwd())
        logging.debug(f"Using default workdir: {workdir}")
    return (abs_cfg, workdir)


def setup_logging(debug: bool, log_levels: str = None, log_file: str = None):
    """Setup logger with debug and module-level configuration"""
    module_levels = None
    if log_levels:
        module_levels = {}
        for pair in log_levels.split(','):
            pair = pair.strip()
            if not pair or '=' not in pair:
                continue
            name, lvl = pair.split('=', 1)
            module_levels[name.strip()] = lvl.strip().upper()

    setup_logger(debug=debug, module_levels=module_levels, log_file=log_file)


def handle_errors(func):
    """Decorator to handle common exceptions"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ConfigurationError as e:
            logging.error(f"Configuration error: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
        except DefinitionError as e:
            logging.error(f"Definition error: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
        except BuildError as e:
            logging.error(f"Build error: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
        except DNSBuilderError as e:
            logging.error(f"An unexpected application error occurred: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
        except FileNotFoundError as e:
            logging.error(f"A required file was not found: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            ctx = click.get_current_context()
            if ctx.obj.get('debug'):
                traceback.print_exc()
            raise click.Abort()
    return wrapper


@handle_errors
def do_build(config_file: str, incremental: bool, graph: str, workdir: str, vfs: bool):
    """Execute build command"""
    abs_cfg, wd = get_paths(config_file, workdir)
    
    cli_fs = create_app_fs(use_vfs=vfs, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    # Choose builder based on incremental flag
    if incremental:
        builder = CachedBuilder(config, graph_output=graph, fs=cli_fs)
        logging.info("Using incremental build with cache")
    else:
        builder = Builder(config, graph_output=graph, fs=cli_fs)
        logging.info("Using standard build")
    
    asyncio.run(builder.run())


@handle_errors
def do_clean(config_file: str, all_images: bool, workdir: str):
    """Execute clean command"""
    if all_images:
        # Clean all dnsb-* images
        logging.info("Cleaning all dnsb-generated shared images...")
        
        # Get all images
        all_imgs = docker.image.list()
        
        # Filter images with 'dnsb-' prefix in tags
        dnsb_images = []
        for img in all_imgs:
            if img.repo_tags and any(tag.startswith('dnsb-') for tag in img.repo_tags):
                dnsb_images.append(img)
        
        if not dnsb_images:
            logging.info("No dnsb-* images found.")
            return
        
        # Remove images
        logging.info(f"Found {len(dnsb_images)} dnsb-* images, removing...")
        removed = 0
        for img in dnsb_images:
            try:
                docker.image.remove(img.id, force=False)
                removed += 1
                tag_name = img.repo_tags[0] if img.repo_tags else img.id[:12]
                logging.debug(f"Removed image: {tag_name}")
            except Exception as e:
                logging.warning(f"Failed to remove image {img.id[:12]}: {e}")
        
        logging.info(f"Successfully cleaned {removed}/{len(dnsb_images)} dnsb-* images.")
    
    elif config_file:
        # Clean project-specific images
        abs_cfg, wd = get_paths(config_file, workdir)
        
        cli_fs = create_app_fs(use_vfs=False, chroot=wd)
        config = Config(abs_cfg, cli_fs)
        
        # Get project name from config
        project_name = config.name
        
        # Get all images
        all_imgs = docker.image.list()
        
        # Filter images with project name prefix
        project_images = []
        for img in all_imgs:
            if img.repo_tags and any(tag.startswith(f'{project_name}-') for tag in img.repo_tags):
                project_images.append(img)
        
        if not project_images:
            logging.info(f"No images found for project '{project_name}'.")
            return
        
        logging.info(f"Cleaning images for project '{project_name}'...")
        removed = 0
        for img in project_images:
            try:
                docker.image.remove(img.id, force=False)
                removed += 1
                tag_name = img.repo_tags[0] if img.repo_tags else img.id[:12]
                logging.debug(f"Removed image: {tag_name}")
            except Exception as e:
                logging.warning(f"Failed to remove image {img.id[:12]}: {e}")
        
        logging.info(f"Successfully cleaned {removed}/{len(project_images)} images for project '{project_name}'.")
    
    else:
        logging.error("Please provide a config file or use --all to clean all dnsb images.")
        raise click.Abort()


@handle_errors
def do_down(config_file: str, workdir: str, remove_volumes: bool, clean_images: bool):
    """Execute down command - stop containers and clean up"""
    abs_cfg, wd = get_paths(config_file, workdir)
    
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    # Get project name from config
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        logging.info("Project may not be built yet.")
        return
    
    logging.info(f"Stopping project '{project_name}'...")
    
    # Use python-on-whales for compose operations
    docker_client = DockerClient(compose_files=[str(compose_file)])
    
    # Determine image removal strategy
    remove_images = 'local' if clean_images else None
    
    try:
        docker_client.compose.down(
            remove_orphans=True,
            volumes=remove_volumes,
            remove_images=remove_images
        )
        logging.info(f"Project '{project_name}' stopped successfully.")
        
        if clean_images:
            logging.info("Project images cleaned.")
        if remove_volumes:
            logging.info("Project volumes removed.")
            
    except Exception as e:
        logging.error(f"Failed to stop project: {e}")
        raise


@handle_errors
def do_run(config_file: str, incremental: bool, graph: str, workdir: str, vfs: bool, detach: bool, build_images: bool):
    """Execute run command - build and start the project"""
    # First, build the project
    logging.info("Building project...")
    do_build(config_file, incremental, graph, workdir, vfs)
    
    # Get paths for compose file
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        raise click.Abort()
    
    logging.info(f"Starting project '{project_name}'...")
    
    # Use python-on-whales to start containers
    docker_client = DockerClient(
        compose_files=[str(compose_file)],
        compose_profiles=["donotstart"]  # Include builder services in project scope
    )
    
    try:
        docker_client.compose.up(
            detach=detach,
            build=build_images,
            remove_orphans=True
        )
        
        if detach:
            logging.info(f"Project '{project_name}' started in background.")
            logging.info(f"Use 'docker-compose -f {compose_file} logs -f' to view logs.")
        else:
            logging.info(f"Project '{project_name}' running. Press Ctrl+C to stop.")
            
    except KeyboardInterrupt:
        logging.info("\nStopping containers...")
        docker_client.compose.down()
        logging.info("Containers stopped.")
    except Exception as e:
        logging.error(f"Failed to start project: {e}")
        raise


@handle_errors
def do_up(config_file: str, workdir: str, detach: bool):
    """Execute up command - start existing project without building"""
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        logging.info("Please run 'dnsb build' first.")
        raise click.Abort()
    
    logging.info(f"Starting project '{project_name}'...")
    
    docker_client = DockerClient(
        compose_files=[str(compose_file)],
        compose_profiles=["donotstart"]  # Include builder services in project scope
    )
    
    try:
        docker_client.compose.up(
            detach=detach,
            remove_orphans=True
        )
        
        if detach:
            logging.info(f"Project '{project_name}' started in background.")
        else:
            logging.info(f"Project '{project_name}' running. Press Ctrl+C to stop.")
    except KeyboardInterrupt:
        logging.info("\nStopping containers...")
        docker_client.compose.down()
        logging.info("Containers stopped.")
    except Exception as e:
        logging.error(f"Failed to start project: {e}")
        raise


@handle_errors
def do_exec(config_file: str, workdir: str, service: str, command: tuple, interactive: bool, user: str):
    """Execute command in a running service container"""
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        raise click.Abort()
    
    docker_client = DockerClient(compose_files=[str(compose_file)])
    
    try:
        # Convert command tuple to list
        cmd = list(command) if command else ['/bin/bash']
        
        # Execute with tty and user options
        docker_client.compose.execute(
            service, 
            cmd,
            tty=interactive,
            user=user
        )
    except Exception as e:
        logging.error(f"Failed to execute command: {e}")
        raise


@handle_errors
def do_logs(config_file: str, workdir: str, services: tuple, follow: bool, tail: int):
    """Show logs from services"""
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        raise click.Abort()
    
    docker_client = DockerClient(compose_files=[str(compose_file)])
    
    try:
        service_list = list(services) if services else None
        docker_client.compose.logs(
            services=service_list,
            follow=follow,
            tail=tail if tail else None
        )
    except KeyboardInterrupt:
        logging.info("\nStopped following logs.")
    except Exception as e:
        logging.error(f"Failed to show logs: {e}")
        raise


@handle_errors
def do_ps(config_file: str, workdir: str):
    """List containers for the project"""
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        raise click.Abort()
    
    docker_client = DockerClient(compose_files=[str(compose_file)])
    
    containers = docker_client.compose.ps()
    
    if not containers:
        logging.info(f"No containers found for project '{project_name}'.")
        return
    
    # Print header
    click.echo(f"{'NAME':<30} {'STATUS':<20} {'PORTS':<40}")
    click.echo("-" * 90)
    
    # Print each container
    for container in containers:
        name = container.name
        status = container.state.status
        ports = ', '.join([f"{p.host_port}->{p.container_port}" for p in container.network_settings.ports.values() if p]) if container.network_settings.ports else ''
        click.echo(f"{name:<30} {status:<20} {ports:<40}")


@handle_errors
def do_restart(config_file: str, workdir: str, services: tuple):
    """Restart services"""
    abs_cfg, wd = get_paths(config_file, workdir)
    cli_fs = create_app_fs(use_vfs=False, chroot=wd)
    config = Config(abs_cfg, cli_fs)
    
    project_name = config.name
    output_dir = wd / "output" / project_name
    compose_file = output_dir / "docker-compose.yml"
    
    if not StdPath(str(compose_file)).exists():
        logging.error(f"docker-compose.yml not found at {compose_file}")
        raise click.Abort()
    
    docker_client = DockerClient(compose_files=[str(compose_file)])
    
    service_list = list(services) if services else None
    service_str = ', '.join(services) if services else 'all services'
    
    logging.info(f"Restarting {service_str}...")
    
    try:
        docker_client.compose.restart(services=service_list)
        logging.info(f"Successfully restarted {service_str}.")
    except Exception as e:
        logging.error(f"Failed to restart services: {e}")
        raise


@click.group()
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('-l', '--log-levels', help="Comma-separated per-module log levels (e.g., 'sub=DEBUG,res=INFO')")
@click.option('-f', '--log-file', help='Path to log file')
@click.version_option(version=__version__, prog_name='dnsbuilder')
@click.pass_context
def cli(ctx, debug, log_levels, log_file):
    """DNS Builder - Build DNS infrastructure from configuration files
    
    \b
    Examples:
      dnsb build config.yml -i    Build with incremental mode
      dnsb clean --all            Clean all shared images
      dnsb ui                     Start web UI
    """
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    setup_logging(debug, log_levels, log_file)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.option('-i', '--incremental', is_flag=True, help='Enable incremental build using cache')
@click.option('-g', '--graph', help='Generate a DOT file for the network topology graph')
@click.option('-w', '--workdir', help="Working directory (use '@config' for config dir, default: cwd)")
@click.option('--vfs', is_flag=True, help='Enable virtual file system')
@click.option('--debug', is_flag=True, help='Enable debug logging for this command')
@click.option('-f', '--log-file', help='Path to log file')
@click.pass_context
def build(ctx, config_file, incremental, graph, workdir, vfs, debug, log_file):
    """Build DNS infrastructure from config file"""
    # Apply debug setting if provided
    if debug and not ctx.obj.get('debug'):
        setup_logging(debug=True, log_levels=None, log_file=log_file)
    do_build(config_file, incremental, graph, workdir, vfs)


@cli.command()
@click.argument('config_file', required=False, shell_complete=complete_config_files)
@click.option('--all', 'all_images', is_flag=True, help='Clean all dnsb-generated shared images')
@click.option('-w', '--workdir', help='Working directory')
@click.pass_context
def clean(ctx, config_file, all_images, workdir):
    """Clean docker images
    
    \b
    Examples:
      dnsb clean test.yml       Clean project-specific images
      dnsb clean --all          Clean all dnsb-* shared images
    """
    do_clean(config_file, all_images, workdir)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.option('-i', '--incremental', is_flag=True, help='Enable incremental build')
@click.option('-g', '--graph', help='Generate topology graph DOT file')
@click.option('-w', '--workdir', help='Working directory')
@click.option('--vfs', is_flag=True, help='Enable virtual file system')
@click.option('-d', '--detach', is_flag=True, help='Run containers in background')
@click.option('--build', is_flag=True, help='Build images before starting')
@click.option('--debug', is_flag=True, help='Enable debug logging for this command')
@click.option('-f', '--log-file', help='Path to log file')
@click.pass_context
def run(ctx, config_file, incremental, graph, workdir, vfs, detach, build, debug, log_file):
    """Build and run the project (build + compose up)
    
    \b
    This command will:
      1. Build the DNS infrastructure
      2. Start all containers using docker-compose
    
    \b
    Examples:
      dnsb run test.yml -d         Build and run in background
      dnsb run test.yml --build    Force rebuild docker images
      dnsb run test.yml --debug    Run with debug logging
    """
    # Apply debug setting if provided
    if debug and not ctx.obj.get('debug'):
        setup_logging(debug=True, log_levels=None, log_file=log_file)
    do_run(config_file, incremental, graph, workdir, vfs, detach, build)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.option('-w', '--workdir', help='Working directory')
@click.option('-d', '--detach', is_flag=True, help='Run containers in background')
@click.pass_context
def up(ctx, config_file, workdir, detach):
    """Start existing project without building
    
    Similar to 'run' but skips the build step. Use this for faster startup
    when you haven't changed the configuration.
    
    \b
    Examples:
      dnsb up test.yml -d          Start project in background
    """
    do_up(config_file, workdir, detach)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.argument('service', required=False, shell_complete=complete_services)
@click.argument('command', nargs=-1)
@click.option('-w', '--workdir', help='Working directory')
@click.option('-u', '--user', help='User to execute as')
@click.pass_context
def exec(ctx, config_file, service, command, workdir, user):
    """Execute command in a running service container
    
    If no command is provided, starts an interactive bash shell.
    
    \b
    Examples:
      dnsb exec test.yml sld                    Start bash in sld container
      dnsb exec test.yml sld sh                 Start sh instead of bash
      dnsb exec test.yml sld cat /etc/hosts     Run a command
      dnsb exec test.yml sld -u root bash       Run as root user
    """
    do_exec(config_file, workdir, service, command, interactive=True, user=user)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.argument('service', required=False, shell_complete=complete_services)
@click.argument('shell_cmd', default='/bin/bash')
@click.option('-w', '--workdir', help='Working directory')
@click.pass_context
def shell(ctx, config_file, service, shell_cmd, workdir):
    """Start an interactive shell in a service container (shortcut for exec)
    
    \b
    Examples:
      dnsb shell test.yml sld          Start bash in sld
      dnsb shell test.yml sld sh       Start sh in sld
    """
    do_exec(config_file, workdir, service, (shell_cmd,), interactive=True, user=None)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.argument('services', nargs=-1, shell_complete=complete_services)
@click.option('-w', '--workdir', help='Working directory')
@click.option('-f', '--follow', is_flag=True, help='Follow log output')
@click.option('-t', '--tail', type=int, help='Number of lines to show from the end')
@click.pass_context
def logs(ctx, config_file, services, workdir, follow, tail):
    """Show logs from services
    
    \b
    Examples:
      dnsb logs test.yml                  Show all logs
      dnsb logs test.yml sld tld          Show logs from sld and tld
      dnsb logs test.yml -f               Follow all logs
      dnsb logs test.yml sld -f -t 100    Follow sld logs, last 100 lines
    """
    do_logs(config_file, workdir, services, follow, tail)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.option('-w', '--workdir', help='Working directory')
@click.pass_context
def ps(ctx, config_file, workdir):
    """List containers and their status
    
    \b
    Examples:
      dnsb ps test.yml
    """
    do_ps(config_file, workdir)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.argument('services', nargs=-1, shell_complete=complete_services)
@click.option('-w', '--workdir', help='Working directory')
@click.pass_context
def restart(ctx, config_file, services, workdir):
    """Restart services
    
    \b
    Examples:
      dnsb restart test.yml              Restart all services
      dnsb restart test.yml sld tld      Restart specific services
    """
    do_restart(config_file, workdir, services)


@cli.command()
@click.argument('config_file', shell_complete=complete_config_files)
@click.option('-w', '--workdir', help='Working directory')
@click.option('-v', '--volumes', is_flag=True, help='Also remove volumes')
@click.option('-c', '--clean', is_flag=True, help='Clean images after stopping')
@click.pass_context
def down(ctx, config_file, workdir, volumes, clean):
    """Stop project containers and clean up resources
    
    By default, this command only stops containers and removes networks,
    keeping images for faster restart. Use -c to also clean images.
    
    \b
    This command will:
      1. Stop and remove all containers for the project
      2. Remove project networks
      3. Remove project volumes (if -v/--volumes is specified)
      4. Remove project images (if -c/--clean is specified)
    
    \b
    Examples:
      dnsb down test.yml           Stop project (keep images for faster restart)
      dnsb down test.yml -c        Stop project and clean images
      dnsb down test.yml -vc       Remove everything including volumes and images
    """
    do_down(config_file, workdir, volumes, clean)


@cli.command()
@click.pass_context
def ui(ctx):
    """Start web UI server"""
    uvicorn.run(app, host="0.0.0.0", port=8000)
