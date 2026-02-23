from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from core.models import CreditCard
import logging

logger = logging.getLogger(__name__)

class BaseOperator(ABC):
    """
    Abstract Base Class for all Operator implementations using Playwright.
    """
    
    def __init__(self, page, card: Optional[CreditCard] = None):
        """
        Initialize with a Playwright Page object.
        """
        self.page = page
        self.card = card
        self.maps = self.Maps

    @property
    @abstractmethod
    def Maps(self) -> Dict[str, str]:
        """
        Return a dictionary of CSS selectors/Xpaths mapped to logical names.
        Example: {'phone_input': '#phone', 'submit_btn': '.submit'}
        """
        pass

    @abstractmethod
    def navigate_to_base_url(self):
        """
        Navigate to the operator's main page.
        """
        pass

    @abstractmethod
    def fill_phone(self, phone_number: str):
        """
        Step 1: Fill in the phone number.
        """
        pass

    @abstractmethod
    def solve_captcha(self) -> bool:
        """
        Step 2: Solve any captcha if present.
        Return True if solved/skipped, False if failed.
        """
        pass

    @abstractmethod
    def select_package(self, package_id: str = None, amount: float = None) -> bool:
        """
        Step 3: Select the package or enter top-up amount.
        """
        pass

    @abstractmethod
    def process_payment(self) -> bool:
        """
        Step 4: Fill credit card details and submit payment.
        Uses self.card
        """
        pass

    @abstractmethod
    def handle_3d_secure(self) -> bool:
        """
        Step 5: Handle 3D Secure verification (waiting for SMS, etc.)
        """
        pass

    def take_screenshot(self, name: str):
        """
        Helper to take screenshots for debugging/logging.
        """
        try:
            self.page.screenshot(path=f"{name}.png")
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
