from abc import ABC, abstractmethod
from typing import Optional

class BaseOperator(ABC):
    """
    Abstract base class for operator automation bots.
    """

    def __init__(self, driver=None):
        self.driver = driver

    @abstractmethod
    def initialize_driver(self):
        """Starts the browser driver (Selenium/Playwright)."""
        pass

    @abstractmethod
    def navigate_to_home(self):
        """Navigates to the operator's homepage."""
        pass

    @abstractmethod
    def select_type(self, type_value: str):
        """Selects 'Paket Yükle' or 'TL Yükle'."""
        pass

    @abstractmethod
    def enter_phone_number(self, phone: str):
        """Enters the phone number."""
        pass

    @abstractmethod
    def solve_captcha(self) -> bool:
        """Solves the captcha if present."""
        pass

    @abstractmethod
    def select_package(self, package_name: str):
        """Navigates tabs and selects the specified package."""
        pass

    @abstractmethod
    def fill_payment_info(self, card_info: dict):
        """Fills credit card and billing details."""
        pass

    @abstractmethod
    def handle_3d_secure(self) -> bool:
        """Handles the 3D secure iframe interaction."""
        pass

    @abstractmethod
    def close(self):
        """Closes the browser."""
        pass
