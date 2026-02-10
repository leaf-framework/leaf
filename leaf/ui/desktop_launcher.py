"""Desktop GUI launcher for LEAF - Simple control panel for users."""

import os
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="desktop_launcher.log")

# Check if tkinter is available
try:
    import tkinter as tk
    from tkinter import font as tkfont

    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    logger.warning("tkinter not available - desktop GUI will not be available")


def is_desktop_environment() -> bool:
    """
    Detect if we're running in a desktop environment.

    Returns:
        True if desktop environment detected, False otherwise
    """
    # First check if tkinter is available at all
    if not TKINTER_AVAILABLE:
        return False

    # Check for common indicators of headless/server environment
    if os.environ.get("CI") == "true":
        return False

    if os.environ.get("LEAF_HEADLESS") == "true":
        return False

    # Check DISPLAY on Linux/Unix
    if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):
        if not os.environ.get("DISPLAY"):
            return False

    # Try to create a test window to verify tkinter actually works
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception as e:
        logger.debug(f"Desktop environment check failed: {e}")
        return False


class LeafDesktopLauncher:
    """Simple desktop GUI launcher for LEAF that shows status and controls."""

    def __init__(self, port: int, on_stop_callback: Callable | None = None, startup_message: str = "Starting LEAF..."):
        """
        Initialize the desktop launcher.

        Args:
            port: Port number where LEAF web interface is running
            on_stop_callback: Function to call when user clicks Stop button
            startup_message: Initial status message to display
        """
        self.port = port
        self.url = f"http://localhost:{port}"
        self.on_stop_callback = on_stop_callback
        self.is_running = True

        # Create main window
        self.root = tk.Tk()
        self.root.title("LEAF - Laboratory Equipment Adapter Framework")
        self.root.geometry("500x350")
        self.root.resizable(False, False)

        # Try to load and set the LEAF icon from SVG
        self.icon_image = None
        try:
            icon_path = Path(__file__).parent / "images" / "icon.svg"
            if icon_path.exists() and TKINTER_AVAILABLE:
                # Try to convert SVG to PhotoImage if cairosvg and PIL available
                try:
                    import io

                    import cairosvg
                    from PIL import Image, ImageTk

                    # Convert SVG to PNG in memory
                    png_data = cairosvg.svg2png(url=str(icon_path), output_width=64, output_height=64)
                    image = Image.open(io.BytesIO(png_data))
                    photo = ImageTk.PhotoImage(image)

                    # Set as window icon
                    self.root.iconphoto(True, photo)
                    # Keep reference to prevent garbage collection
                    self.icon_image = photo
                    logger.debug("LEAF icon loaded successfully from SVG")
                except ImportError:
                    logger.debug("cairosvg or PIL not available - icon rendering skipped")
                except Exception as e:
                    logger.debug(f"Could not render SVG icon: {e}")
        except Exception as e:
            logger.debug(f"Could not set window icon: {e}")

        # Configure colors
        bg_color = "#f5f5f5"
        header_color = "#434A5A"
        button_color = "#4096FF"
        stop_button_color = "#dc2626"

        self.root.configure(bg=bg_color)

        # Create header with logo/title
        header_frame = tk.Frame(self.root, bg=header_color, height=100)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)

        # Try to load SVG logo for display in header
        self.logo_image = None
        try:
            icon_path = Path(__file__).parent / "images" / "icon.svg"
            if icon_path.exists() and TKINTER_AVAILABLE:
                try:
                    import io

                    import cairosvg
                    from PIL import Image, ImageTk

                    # Convert SVG to PNG for header display (larger size)
                    png_data = cairosvg.svg2png(url=str(icon_path), output_width=60, output_height=60)
                    image = Image.open(io.BytesIO(png_data))
                    self.logo_image = ImageTk.PhotoImage(image)
                    logger.debug("LEAF logo loaded for header display")
                except Exception as e:
                    logger.debug(f"Could not render SVG logo for header: {e}")
        except Exception as e:
            logger.debug(f"Could not load logo for header: {e}")

        # Center container for logo, title and subtitle
        title_container = tk.Frame(header_frame, bg=header_color)
        title_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Logo image (if available) - on the left
        if self.logo_image:
            logo_label = tk.Label(title_container, image=self.logo_image, bg=header_color)
            logo_label.pack(side=tk.LEFT, padx=(0, 15))

        # Text container for title and subtitle
        text_container = tk.Frame(title_container, bg=header_color)
        text_container.pack(side=tk.LEFT)

        # LEAF Title
        title_font = tkfont.Font(family="Helvetica", size=26, weight="bold")
        title_label = tk.Label(text_container, text="LEAF", font=title_font, bg=header_color, fg="white")
        title_label.pack(anchor=tk.W)

        # Subtitle
        subtitle_font = tkfont.Font(family="Helvetica", size=10)
        subtitle_label = tk.Label(
            text_container,
            text="Laboratory Equipment Adapter Framework",
            font=subtitle_font,
            bg=header_color,
            fg="#E0E7FF",
        )
        subtitle_label.pack(anchor=tk.W)

        # Main content frame
        content_frame = tk.Frame(self.root, bg=bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        # Status label
        status_font = tkfont.Font(family="Helvetica", size=12)
        self.status_label = tk.Label(content_frame, text=startup_message, font=status_font, bg=bg_color, fg="#333333")
        self.status_label.pack(pady=(0, 10))

        # URL display
        url_font = tkfont.Font(family="Courier", size=11)
        url_frame = tk.Frame(content_frame, bg="white", relief=tk.SOLID, borderwidth=1)
        url_frame.pack(pady=10, fill=tk.X)

        self.url_label = tk.Label(url_frame, text=self.url, font=url_font, bg="white", fg="#2563EB", cursor="hand2")
        self.url_label.pack(pady=8, padx=10)
        self.url_label.bind("<Button-1>", lambda e: self.open_browser())

        # Buttons frame
        buttons_frame = tk.Frame(content_frame, bg=bg_color)
        buttons_frame.pack(pady=20)

        # Open Browser button
        button_font = tkfont.Font(family="Helvetica", size=11, weight="bold")
        self.open_button = tk.Button(
            buttons_frame,
            text="Open Browser",
            font=button_font,
            bg=button_color,
            fg="black",
            activebackground="#3182CE",
            activeforeground="black",
            relief=tk.FLAT,
            cursor="hand2",
            padx=20,
            pady=10,
            command=self.open_browser,
        )
        self.open_button.pack(side=tk.LEFT, padx=5)

        # Stop button
        self.stop_button = tk.Button(
            buttons_frame,
            text="Stop LEAF",
            font=button_font,
            bg=stop_button_color,
            fg="black",
            activebackground="#991b1b",
            activeforeground="black",
            relief=tk.FLAT,
            cursor="hand2",
            padx=20,
            pady=10,
            command=self.stop_leaf,
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # Footer info
        footer_frame = tk.Frame(self.root, bg=bg_color)
        footer_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        info_font = tkfont.Font(family="Helvetica", size=9)
        info_label = tk.Label(
            footer_frame, text="Documentation: leaf.systemsbiology.nl", font=info_font, bg=bg_color, fg="#666666"
        )
        info_label.pack()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

        logger.info(f"Desktop launcher initialized for {self.url}")

    def update_status(self, message: str, color: str = "#333333"):
        """Update the status label."""
        try:
            self.status_label.configure(text=message, fg=color)
            self.root.update_idletasks()
        except Exception as e:
            logger.error(f"Error updating status: {e}")

    def open_browser(self):
        """Open the LEAF web interface in the default browser."""
        logger.info(f"Opening browser to {self.url}")
        try:
            webbrowser.open(self.url)
            self.update_status("Browser opened", "#059669")
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            self.update_status(f"Failed to open browser: {e}", "#dc2626")

    def stop_leaf(self):
        """Stop LEAF and close the launcher."""
        logger.info("User requested LEAF shutdown via desktop launcher")
        self.update_status("Stopping LEAF...", "#dc2626")
        self.is_running = False

        # Disable buttons
        self.open_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.DISABLED)

        # Call the stop callback in a separate thread
        if self.on_stop_callback:

            def stop_thread():
                try:
                    self.on_stop_callback()
                except Exception as e:
                    logger.error(f"Error in stop callback: {e}")
                finally:
                    # Close the window after stopping
                    try:
                        self.root.after(1000, self.root.destroy)
                    except Exception:
                        pass

            threading.Thread(target=stop_thread, daemon=True).start()
        else:
            # If no callback, just close
            self.root.after(500, self.root.destroy)

    def on_window_close(self):
        """Handle window close button."""
        logger.info("User closed desktop launcher window")
        self.stop_leaf()

    def run(self):
        """Run the desktop launcher main loop."""
        logger.info("Starting desktop launcher GUI")
        try:
            # Auto-open browser on startup after a short delay
            self.root.after(1500, self.open_browser)

            # Start the GUI main loop
            self.root.mainloop()
            logger.info("Desktop launcher GUI closed")
        except Exception as e:
            logger.error(f"Desktop launcher error: {e}", exc_info=True)
        finally:
            self.is_running = False


def run_desktop_launcher(
    port: int, on_stop_callback: Callable | None = None, startup_message: str = "LEAF is starting..."
) -> LeafDesktopLauncher:
    """
    Run the desktop launcher GUI.

    Args:
        port: Port number where LEAF web interface is running
        on_stop_callback: Function to call when user clicks Stop button
        startup_message: Initial status message

    Returns:
        LeafDesktopLauncher instance
    """
    launcher = LeafDesktopLauncher(port, on_stop_callback, startup_message)

    # Update status after initialization
    launcher.update_status("✓ LEAF is running", "#059669")

    return launcher
