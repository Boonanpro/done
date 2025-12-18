"""
LINE Desktop (PC版) Automation Tools using pywinauto

This module provides automation for LINE PC application on Windows.
⚠️ WARNING: This may violate LINE's Terms of Service. Use at your own risk.
"""
import os
import time
import random
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Check if running on Windows
try:
    from pywinauto.application import Application
    from pywinauto.findwindows import ElementNotFoundError
    from pywinauto import Desktop
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    logger.warning("pywinauto is not available. LINE desktop automation will not work.")


@dataclass
class LineMessage:
    """Represents a LINE message"""
    sender: str
    content: str
    timestamp: Optional[str] = None
    is_from_me: bool = False


class LineDesktopController:
    """
    Controller for LINE PC application using pywinauto.
    
    Requires:
    - LINE PC版 installed
    - User already logged in to LINE
    - LINE application running
    """
    
    # Common LINE PC installation paths
    DEFAULT_LINE_PATHS = [
        r"C:\Program Files\LINE\LINE.exe",
        r"C:\Program Files (x86)\LINE\LINE.exe",
        os.path.expanduser(r"~\AppData\Local\LINE\LINE.exe"),
    ]
    
    def __init__(self):
        """Initialize the LINE Desktop Controller"""
        if not PYWINAUTO_AVAILABLE:
            raise RuntimeError("pywinauto is not installed. Run: pip install pywinauto")
        
        self._app: Optional[Application] = None
        self._main_window = None
        self._connected = False
    
    def _human_delay(self, min_ms: int = 100, max_ms: int = 500):
        """Add human-like delay between actions"""
        delay = random.randint(min_ms, max_ms) / 1000
        time.sleep(delay)
    
    def find_line_path(self) -> Optional[str]:
        """Find LINE executable path"""
        for path in self.DEFAULT_LINE_PATHS:
            if os.path.exists(path):
                return path
        return None
    
    def is_line_running(self) -> bool:
        """Check if LINE is already running"""
        try:
            desktop = Desktop(backend="uia")
            windows = desktop.windows()
            for win in windows:
                try:
                    if "LINE" in win.window_text():
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking if LINE is running: {e}")
            return False
    
    def connect(self, start_if_not_running: bool = False) -> bool:
        """
        Connect to LINE PC application.
        
        Args:
            start_if_not_running: If True, start LINE if not running
            
        Returns:
            True if connected successfully
        """
        try:
            if self.is_line_running():
                # Connect to existing LINE window
                self._app = Application(backend="uia").connect(title_re=".*LINE.*", timeout=10)
                logger.info("Connected to existing LINE window")
            elif start_if_not_running:
                # Start LINE
                line_path = self.find_line_path()
                if not line_path:
                    logger.error("LINE executable not found")
                    return False
                
                self._app = Application(backend="uia").start(line_path)
                time.sleep(5)  # Wait for LINE to start
                logger.info(f"Started LINE from {line_path}")
            else:
                logger.error("LINE is not running")
                return False
            
            # Get main window
            self._main_window = self._app.window(title_re=".*LINE.*")
            self._main_window.wait("visible", timeout=30)
            self._connected = True
            
            logger.info("Successfully connected to LINE")
            return True
            
        except ElementNotFoundError as e:
            logger.error(f"Could not find LINE window: {e}")
            return False
        except Exception as e:
            logger.error(f"Error connecting to LINE: {e}")
            return False
    
    def is_connected(self) -> bool:
        """Check if connected to LINE"""
        if not self._connected or not self._main_window:
            return False
        try:
            # Try to access the window to verify connection
            self._main_window.exists()
            return True
        except Exception:
            self._connected = False
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get current LINE connection status"""
        return {
            "connected": self.is_connected(),
            "line_running": self.is_line_running(),
            "line_installed": self.find_line_path() is not None,
        }
    
    def search_friend(self, search_term: str) -> bool:
        """
        Search for a friend in LINE.
        
        Args:
            search_term: Friend name or ID to search
            
        Returns:
            True if search was initiated successfully
        """
        if not self.is_connected():
            logger.error("Not connected to LINE")
            return False
        
        try:
            self._human_delay()
            
            # Find and click search box
            # Note: The actual control names may vary by LINE version
            search_box = self._main_window.child_window(
                control_type="Edit",
                found_index=0
            )
            search_box.click_input()
            self._human_delay()
            
            # Clear and type search term
            search_box.set_text("")
            self._human_delay(50, 150)
            
            # Type character by character for human-like behavior
            for char in search_term:
                search_box.type_keys(char, with_spaces=True)
                self._human_delay(30, 100)
            
            self._human_delay(500, 1000)  # Wait for search results
            
            logger.info(f"Searched for: {search_term}")
            return True
            
        except Exception as e:
            logger.error(f"Error searching for friend: {e}")
            return False
    
    def select_chat(self, chat_name: str) -> bool:
        """
        Select a chat by name.
        
        Args:
            chat_name: Name of the chat/friend to select
            
        Returns:
            True if chat was selected successfully
        """
        if not self.is_connected():
            logger.error("Not connected to LINE")
            return False
        
        try:
            # First search for the chat
            if not self.search_friend(chat_name):
                return False
            
            self._human_delay(500, 1000)
            
            # Try to find and click the chat item
            # This might need adjustment based on LINE's UI structure
            chat_list = self._main_window.child_window(control_type="List")
            items = chat_list.children()
            
            for item in items:
                try:
                    if chat_name.lower() in item.window_text().lower():
                        item.click_input()
                        self._human_delay()
                        logger.info(f"Selected chat: {chat_name}")
                        return True
                except Exception:
                    continue
            
            logger.warning(f"Chat not found: {chat_name}")
            return False
            
        except Exception as e:
            logger.error(f"Error selecting chat: {e}")
            return False
    
    def send_message(self, message: str) -> bool:
        """
        Send a message in the currently selected chat.
        
        Args:
            message: Message text to send
            
        Returns:
            True if message was sent successfully
        """
        if not self.is_connected():
            logger.error("Not connected to LINE")
            return False
        
        try:
            self._human_delay()
            
            # Find message input box (usually at bottom of chat)
            # The control type and properties may vary
            message_box = self._main_window.child_window(
                control_type="Edit",
                found_index=-1  # Last edit box (usually the message input)
            )
            message_box.click_input()
            self._human_delay()
            
            # Type message character by character
            for char in message:
                message_box.type_keys(char, with_spaces=True, pause=0.02)
                self._human_delay(20, 80)
            
            self._human_delay(200, 500)
            
            # Press Enter to send
            message_box.type_keys("{ENTER}")
            
            self._human_delay()
            logger.info(f"Sent message: {message[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    def send_message_to(self, recipient: str, message: str) -> bool:
        """
        Send a message to a specific recipient.
        
        Args:
            recipient: Name of the friend/chat
            message: Message text to send
            
        Returns:
            True if message was sent successfully
        """
        if not self.select_chat(recipient):
            return False
        
        return self.send_message(message)
    
    def get_window_info(self) -> Dict[str, Any]:
        """
        Get information about the LINE window structure.
        Useful for debugging and understanding the UI.
        """
        if not self.is_connected():
            return {"error": "Not connected to LINE"}
        
        try:
            info = {
                "title": self._main_window.window_text(),
                "controls": []
            }
            
            for ctrl in self._main_window.descendants():
                try:
                    info["controls"].append({
                        "type": ctrl.element_info.control_type,
                        "name": ctrl.element_info.name,
                        "class": ctrl.element_info.class_name,
                    })
                except Exception:
                    continue
            
            return info
            
        except Exception as e:
            return {"error": str(e)}
    
    def disconnect(self):
        """Disconnect from LINE (does not close the application)"""
        self._app = None
        self._main_window = None
        self._connected = False
        logger.info("Disconnected from LINE")


# Singleton instance
_line_controller: Optional[LineDesktopController] = None


def get_line_controller() -> LineDesktopController:
    """Get the singleton LINE controller instance"""
    global _line_controller
    if _line_controller is None:
        _line_controller = LineDesktopController()
    return _line_controller
