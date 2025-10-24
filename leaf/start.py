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

from dateparser.data.date_translation_data import el
import yaml  # type: ignore
from leaf.ui.interface import start_nicegui

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel
from leaf.modules.output_modules.output_module import OutputModule
from leaf.registry.registry import discover_from_config
from leaf.utility.config_utils import substitute_env_variables
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.logger.logger_utils import set_log_dir
from leaf.utility.logger.logger_utils import set_global_log_level
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
        default=8080,
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
        logger.warn("No adapters installed.")

def stop_all_adapters() -> None:
    """Gracefully stops all running adapters and joins threads."""
    logger.info("Stopping all adapters.")
    adapter_timeout = 10
    count = 0
    while len(adapters) == 0:
        time.sleep(0.5)
        count += 1
        if count >= adapter_timeout:
            raise AdapterBuildError("Cannot stop adapter, likely hasn't started before shutdown.")

    for adapter in adapters:
        if adapter.is_running():
            adapter.withdraw()

    for adapter in adapters:
        try:
            adapter.stop()
            logger.info(f"Adapter for {adapter} stopped successfully.")
        except Exception as e:
            logger.error(f"Error stopping adapter: {e}")

    for thread in adapter_threads:
        thread.join()


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
    error_handler: ErrorHolder
) -> None:
    """Initializes, runs, and monitors equipment adapters."""
    global adapter_threads

    cooldown_period_error = 5
    cooldown_period_warning = 1
    max_warning_retries = 2
    client_warning_retry_count = 0

    try:
        for equipment_instance in equipment_instances:
            simulated = equipment_instance["equipment"].pop("simulation", None)
            instance_id = equipment_instance["equipment"]["data"]["instance_id"]
            adapter = process_instance(equipment_instance["equipment"], output)
            if adapter is None:
                continue

            adapters.append(adapter)
            

            if simulated:
                if not hasattr(adapter, "simulate"):
                    raise AdapterBuildError("Adapter does not support simulation.")
                logger.info(f"Simulator started for instance {instance_id}.")
                thread = run_simulation_in_thread(adapter, **simulated)
            else:
                logger.info(f"Proxy started for instance {instance_id}.")
                thread = start_all_adapters_in_threads([adapter])[0]

            adapter_threads.append(thread)

        while True:
            time.sleep(1)
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
    """Ensures configuration file is available in the expected directory."""
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_dir = os.path.join(script_dir, "config")
    os.makedirs(config_dir, exist_ok=True)

    if args.config and os.path.exists(args.config):
        logger.info(f"Configuration file {args.config} found.")
        with open(args.config, "r") as src:
            content = src.read()
        with open(os.path.join(config_dir, CONFIG_FILE_NAME), "w") as dest:
            if not content.strip():
                logger.warning(f"Configuration file {args.config} is empty, skipping copy.")
            else:
                dest.write(content)
                logger.info(f"Configuration file {CONFIG_FILE_NAME} successfully created.")

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

    # Start NiceGUI in a separate thread
    nicegui_thread: threading.Thread|None = None
    if not context.args.nogui:
        logger.info("Running LEAF with NiceGUI interface.")
        nicegui_thread = threading.Thread(target=start_nicegui, args=(context.args.port,), daemon=True)
        nicegui_thread.start()
    else:
        logger.info("Running LEAF in headless mode without NiceGUI interface.")

    welcome_message()

    # Load configuration file first.
    if not context.args.config:
        logger.info("No configuration file provided, using default configuration...")
        # Load default configuration
        from pathlib import Path
        context.args.config = Path(os.path.dirname(os.path.realpath(__file__))) / "config" / "configuration.yaml"
        logger.info(f"Using default configuration: {context.args.config}")
    
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

    if context.args.debug:
        set_global_log_level(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled.")

    create_configuration(context.args)

    if not getattr(context.args, 'no_signals', False):
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        sys.excepthook = handle_exception

    if context.config_yaml is not None:
        logger.info(context.__dict__)
        logger.info(f"Configuration: {context.args.config} loaded.")
        logger.info(f"\n{context.config_yaml}\n")
        context.error_handler = ErrorHolder()
        context.output = build_output_module(config, context.error_handler)
        if context.output is not None:
            logger.debug("Output module built successfully.")
            run_adapters(
                config.get("EQUIPMENT_INSTANCES", []),
                context.output,
                context.error_handler,
            )
    # Wait for NiceGUI thread to finish
    if nicegui_thread is not None:
        nicegui_thread.join()
        logger.info("NiceGUI thread has finished.")
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