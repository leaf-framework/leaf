##################################
#
#            PACKAGES
#
###################################

import argparse
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Optional, Type

import yaml  # type: ignore

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel
from leaf.modules.output_modules.output_module import OutputModule
from leaf.registry.registry import discover_from_config
from leaf.ui.interface import start_nicegui
from leaf.utility.config_utils import substitute_env_variables
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.logger.logger_utils import set_global_log_level
from leaf.utility.logger.logger_utils import set_log_dir
from leaf.utility.running_utilities import build_output_module
from leaf.utility.running_utilities import handle_disabled_modules
from leaf.utility.running_utilities import process_instance
from leaf.utility.running_utilities import run_simulation_in_thread
from leaf.utility.running_utilities import start_all_adapters_in_threads

##################################
#
#            VARIABLES
#
###################################

CACHE_DIR = "cache"
ERROR_LOG_DIR = os.path.join(CACHE_DIR, "error_logs")
LOG_FILE = "global.log"
ERROR_LOG_FILE = "global_error.log"
CONFIG_FILE_NAME = "configuration.yaml"

set_log_dir(ERROR_LOG_DIR)
logger = get_logger(__name__, log_file=LOG_FILE, error_log_file=ERROR_LOG_FILE)

adapters: list[Any] = []
adapter_threads: list[threading.Thread] = []

output_disable_time = 10


class AppContext:
    """Context container to hold shared application state."""
    def __init__(self) -> None:
        self.output: Optional[OutputModule] = None
        self.error_handler: Optional[ErrorHolder] = None
        self.config_yaml: Optional[str] = None
        self.args: Optional[argparse.Namespace] = None
        self.external_adapter: Optional[str] = None

context = AppContext()

##################################
#
#            FUNCTIONS
#
###################################

def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(
        description="Proxy to monitor equipment and send data to the cloud."
    )


    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.")

    # Gui argument
    parser.add_argument(
        "--nogui",
        action="store_true",
        help="Run the proxy without the NiceGUI interface. Useful for headless environments.",
    )

    # Port argument
    parser.add_argument(
        "--port",
        type=int,
        default=4242,
        help="Port to run the NiceGUI interface on. Default is 8080.",
    )
        
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        help="The configuration file to use.",
    )
    parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="The path to the directory of the adapter to use.",
        default=None
    )

    parser.add_argument("--shutdown", action="store_true", help=argparse.SUPPRESS)
    
    parser.add_argument(
        "--no-signals",
        action="store_true",
        help=argparse.SUPPRESS # Hidden option for testing purposes only
    )

    return parser.parse_args(args=args)


def welcome_message() -> None:
    """Displays a welcome banner and basic startup info."""
    logger.info("""\n\n ##:::::::'########::::'###::::'########:
 ##::::::: ##.....::::'## ##::: ##.....::
 ##::::::: ##::::::::'##:. ##:: ##:::::::
 ##::::::: ######:::'##:::. ##: ######:::
 ##::::::: ##...:::: #########: ##...::::
 ##::::::: ##::::::: ##.... ##: ##:::::::
 ########: ########: ##:::: ##: ##:::::::
........::........::..:::::..::..::::::::\n\n""")
    logger.info("Welcome to the LEAF Proxy.")
    logger.info("Starting the proxy.")
    logger.info("Press Ctrl+C to stop the proxy.")
    logger.info("For more information, visit leaf.systemsbiology.nl")
    logger.info("For help, use the -h flag.")
    logger.info("#" * 40)
    # Obtain all installed adapters
    from leaf.registry.discovery import get_all_adapter_codes
    adapter_codes = get_all_adapter_codes()
    if len(adapter_codes) > 0:
        logger.info("Installed adapters:")
        for adapter_code in adapter_codes:
            logger.info(f"- {adapter_code['code']}")
    else:
        logger.warning("No adapters installed.")

def stop_all_adapters() -> None:
    """Gracefully stops all running adapters and joins threads."""
    # If no adapters were started, nothing to stop
    if len(adapters) == 0:
        logger.info("No adapters to stop.")
        return

    logger.info(f"Stopping {len(adapters)} adapter(s).")

    for adapter in adapters:
        try:
            if adapter.is_running():
                adapter.withdraw()
        except Exception as e:
            logger.error(f"Error withdrawing adapter {adapter}: {e}")

    for adapter in adapters:
        try:
            adapter.stop()
            logger.info(f"Adapter for {adapter} stopped successfully.")
        except Exception as e:
            logger.error(f"Error stopping adapter {adapter}: {e}")

    for thread in adapter_threads:
        try:
            thread.join(timeout=5)
        except Exception as e:
            logger.error(f"Error joining thread: {e}")


def signal_handler(signal_received: int, 
                   frame: Optional[Any]) -> None:
    """Handles termination signals like Ctrl+C or kill."""
    logger.info("Signal received, shutting down gracefully.")
    stop_all_adapters()
    sys.exit(0)


def handle_exception(exc_type: Type[BaseException], 
                     exc_value: BaseException, 
                     exc_traceback: Any) -> None:
    """Handles uncaught exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value,
                                                 exc_traceback))
    stop_all_adapters()


def error_shutdown(error: Exception, output: OutputModule, 
                   unhandled_errors: Optional[list[Any]] = None) -> None:
    """Handles critical failure by shutting down all components."""
    logger.error(f"Critical error encountered: {error}. Shutting down.", 
                 exc_info=error)
    for adapter in adapters:
        if unhandled_errors is not None:
            adapter.transmit_errors(unhandled_errors)
            time.sleep(0.1)
        adapter.transmit_errors()
        time.sleep(0.1)
    stop_all_adapters()
    time.sleep(5)
    output.disconnect()


def run_adapters(
    equipment_instances: list[dict[str, Any]],
    output: OutputModule,
    error_handler: ErrorHolder,
    nicegui_thread: Optional[threading.Thread] = None
) -> None:
    """Initializes, runs, and monitors equipment adapters."""
    global adapter_threads

    cooldown_period_error = 5
    cooldown_period_warning = 1
    max_warning_retries = 2
    client_warning_retry_count = 0
    gui_was_alive = nicegui_thread.is_alive() if nicegui_thread else False

    try:
        for equipment_instance in equipment_instances:
            try:
                simulated = equipment_instance["equipment"].pop("simulation", None)
                instance_id = equipment_instance["equipment"]["data"]["instance_id"]
                adapter_name = equipment_instance["equipment"].get("adapter", "Unknown")

                logger.info(f"Attempting to start adapter '{adapter_name}' for instance '{instance_id}'...")

                try:
                    adapter = process_instance(equipment_instance["equipment"], output)
                except Exception as e:
                    adapter = None
                    logger.error(f"Failed to process instance '{instance_id}': {e}", exc_info=True)

                if adapter is None:
                    logger.warning(f"Adapter '{adapter_name}' for instance '{instance_id}' could not be initialized. Skipping.")
                    continue

                adapters.append(adapter)

                if simulated:
                    if not hasattr(adapter, "simulate"):
                        logger.error(f"Adapter '{adapter_name}' does not support simulation. Skipping instance '{instance_id}'.")
                        continue
                    logger.info(f"Simulator started for instance {instance_id}.")
                    thread = run_simulation_in_thread(adapter, **simulated)
                else:
                    logger.info(f"Proxy started for instance {instance_id}.")
                    thread = start_all_adapters_in_threads([adapter])[0]

                adapter_threads.append(thread)

            except Exception as e:
                logger.error(f"Failed to start adapter '{adapter_name}' for instance '{instance_id}': {e}", exc_info=True)
                logger.warning(f"Continuing with other adapters...")

        # If no adapters started successfully, log warning but don't crash
        if len(adapters) == 0:
            logger.warning("No adapters were started successfully. LEAF will continue running but no data will be collected.")
            logger.info("Check your configuration file and ensure required adapters are installed.")
            # Keep LEAF running even with no adapters (for UI access)
            while True:
                time.sleep(10)
                # Monitor NiceGUI thread status even when no adapters running
                if nicegui_thread and gui_was_alive and not nicegui_thread.is_alive():
                    logger.warning("NiceGUI web interface has stopped unexpectedly.")
                    gui_was_alive = False

        while True:
            time.sleep(1)

            # Monitor NiceGUI thread status
            if nicegui_thread and gui_was_alive and not nicegui_thread.is_alive():
                logger.warning("NiceGUI web interface has stopped unexpectedly during adapter operation.")
                gui_was_alive = False

            if all(not t.is_alive() for t in adapter_threads):
                logger.info("All adapters have stopped.")
                break

            cur_errors = error_handler.get_unseen_errors()

            for adapter in adapters:
                adapter.transmit_errors(cur_errors)
                time.sleep(0.1)

            for error, _ in cur_errors:
                if error.severity == SeverityLevel.CRITICAL:
                    return error_shutdown(error, output, 
                                          error_handler.get_unseen_errors())

                elif error.severity == SeverityLevel.ERROR:
                    logger.error(f"Error, resetting adapters: {error}", exc_info=error)
                    error_shutdown(error, output)
                    time.sleep(cooldown_period_error)
                    output.connect()
                    adapter_threads = start_all_adapters_in_threads(adapters)

                elif error.severity == SeverityLevel.WARNING:
                    if isinstance(error, ClientUnreachableError):
                        logger.warning(
                            f"Client unreachable (attempt {client_warning_retry_count + 1}): {error}",
                            exc_info=error)
                        # Only disable/reconnect if the error is from the primary output module
                        if hasattr(error, 'client') and error.client == output:
                            if output.is_enabled():
                                if client_warning_retry_count >= max_warning_retries:
                                    logger.error(f"Disabling client {output.__class__.__name__}.",
                                                 exc_info=error)
                                    output.disable()
                                    client_warning_retry_count = 0
                                else:
                                    client_warning_retry_count += 1
                                    output.disconnect()
                                    time.sleep(cooldown_period_warning)
                                    output.connect()
                        # If error is from a fallback module, just log it (don't disable primary)
                    else:
                        logger.warning(f"Warning encountered: {error}",
                                       exc_info=error)

                elif error.severity == SeverityLevel.INFO:
                    logger.info(f"Informational error: {error}", 
                                exc_info=error)

            if not output.is_enabled():
                logger.debug("Output module is disabled, attempting to reconnect.")
            handle_disabled_modules(output, output_disable_time)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down.")
    except Exception as e:
        logger.error(f"Unexpected error occurred: {e}", exc_info=True)
    finally:
        stop_all_adapters()
        logger.info("Proxy stopped.")

    logger.info("All adapter threads have been stopped.")
    return None


def create_configuration(args: argparse.Namespace) -> None:
    """Ensures configuration file is available in the expected directory.

    NOTE: This function is kept for backward compatibility but should not
    overwrite the config path when using editable installs or explicit paths.
    """
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_dir = os.path.join(script_dir, "config")
    os.makedirs(config_dir, exist_ok=True)

    # If config already points to an existing file, don't change it
    if args.config and os.path.exists(args.config):
        logger.info(f"Configuration file {args.config} already exists, using as-is.")
        # Don't overwrite args.config - use the existing path
        return

    # Only create/copy if no config exists
    logger.warning(f"No configuration file found at {args.config}, creating default.")
    args.config = os.path.join(config_dir, CONFIG_FILE_NAME)


##################################
#
#             MAIN
#
###################################

def main(args: Optional[list[str]] = None) -> None:
    """Main entry point for the LEAF proxy."""
    context = AppContext()
    context.args = parse_args(args)

    if context.args.shutdown:
        logger.info("Shutdown signal received. Shutting down the LEAF framework.")
        return

    logger.info("Context arguments parsed: %s", context.args)

    # Set debug logging BEFORE any other modules are loaded
    if context.args.debug:
        set_global_log_level(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled.")

    # Determine configuration file path first (needed for UI)
    if not context.args.config:
        logger.info("No configuration file provided, using default configuration...")
        # Load default configuration
        from pathlib import Path
        context.args.config = Path(os.path.dirname(os.path.realpath(__file__))) / "config" / "configuration.yaml"
        logger.info(f"Using default configuration: {context.args.config}")
        logger.info(f"Configuration file exists: {os.path.exists(context.args.config)}")
        logger.info(f"Configuration file size: {os.path.getsize(context.args.config) if os.path.exists(context.args.config) else 'N/A'} bytes")

    # Start NiceGUI in a separate thread (after config path is determined)
    # Capture the config path NOW before create_configuration() changes it
    ui_config_path = context.args.config
    ui_port = context.args.port

    def start_nicegui_wrapper():
        """Wrapper to catch and log any exceptions from the UI thread."""
        try:
            # Use captured values, not context.args which may change
            start_nicegui(ui_port, ui_config_path)
        except Exception as e:
            logger.error(f"NiceGUI thread crashed with error: {e}", exc_info=True)
            raise

    nicegui_thread: threading.Thread|None = None
    if not context.args.nogui:
        logger.info("Running LEAF with NiceGUI interface.")
        logger.info(f"UI will use config file: {ui_config_path}")
        nicegui_thread = threading.Thread(
            target=start_nicegui_wrapper,
            daemon=True,  # Daemon so it dies when main thread (adapters) exits
            name="NiceGUI-Thread"
        )
        nicegui_thread.start()
        logger.info("NiceGUI thread started successfully.")
        # Give the UI server a moment to initialize
        time.sleep(0.5)
    else:
        logger.info("Running LEAF in headless mode without NiceGUI interface.")

    welcome_message()
    
    if not os.path.exists(context.args.config):
        raise FileNotFoundError(
            f"Configuration file {context.args.config} does not exist. Please provide a valid configuration file."
        )
    try:
        with open(context.args.config, "r") as f:
            content = f.read()
            if not content.strip():
                logger.error("Configuration file is empty, please provide a valid configuration.")
                return
            # Substitute environment variables before parsing YAML
            content = substitute_env_variables(content)
            config = yaml.safe_load(content)
            context.config_yaml = yaml.dump(config, indent=4)
            discover_from_config(config, context.args.path)
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML configuration.", exc_info=e)
        return
    except ValueError as e:
        logger.error(f"Environment variable substitution failed: {e}")
        return

    create_configuration(context.args)

    if not getattr(context.args, 'no_signals', False):
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        sys.excepthook = handle_exception


    if context.config_yaml is not None:
        logger.info(context.__dict__)
        pretty = yaml.safe_dump(
            yaml.safe_load(context.config_yaml) if isinstance(context.config_yaml, str) else context.config_yaml,
            sort_keys=False,
            default_flow_style=False,
            indent=2
        )
        logger.info(f"Configuration: {context.args.config} loaded.\n{pretty}")
        context.error_handler = ErrorHolder()
        context.output = build_output_module(config, context.error_handler)
        if context.output is not None:
            logger.debug("Output module built successfully.")
            if config.get("EQUIPMENT_INSTANCES", None) is None or len(config.get("EQUIPMENT_INSTANCES", [])) == 0:
                logger.warning("No equipment instances found in configuration.")
                logger.info("LEAF will run in UI-only mode. Use the Configuration tab to add equipment instances.")
                # Keep running for UI access even with no adapters
                if nicegui_thread is not None and nicegui_thread.is_alive():
                    logger.info("Running in UI-only mode. Press Ctrl+C to stop.")
                    try:
                        # Keep main thread alive so daemon UI thread continues
                        while True:
                            time.sleep(1)
                            # Check if UI crashed
                            if not nicegui_thread.is_alive():
                                logger.error("NiceGUI thread stopped unexpectedly in UI-only mode.")
                                break
                    except KeyboardInterrupt:
                        logger.info("Keyboard interrupt received.")
            else:
                run_adapters(
                    config.get("EQUIPMENT_INSTANCES", []),
                    context.output,
                    context.error_handler,
                    nicegui_thread,
                )

    # Main thread (adapters) finished, daemon UI thread will stop automatically
    logger.info("LEAF Proxy has stopped.")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        logger.error("An error occurred in the main execution.", exc_info=e)
        sys.exit(1)
    finally:
        logger.info("Exiting LEAF Proxy.")
        sys.exit(0)