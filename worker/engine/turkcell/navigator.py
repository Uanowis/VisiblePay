
import time
import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

def handle_cookies(page: Page):
    try:
        # List of potential cookie button selectors
        selectors = [
            'button#onetrust-accept-btn-handler',
            '#onetrust-accept-btn-handler', 
            '.onetrust-close-btn-handler',
            'button[class*="cookie-policy-popup__button"]',
             # Any other generic "Accept" buttons
            'button:has-text("Kabul Et")',
            'button:has-text("Tümünü Kabul Et")',
            'button:has-text("Hepsini Kabul Et")',
            'button:has-text("Allow All")',
            'button:has-text("Accept All")',
            '#onetrust-accept-btn-handler',
            '.eu-cookie-compliance-default-button',
            'button[id*="cookie"]',
            'a:has-text("Kabul Et")'
        ]
        
        for selector in selectors:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                logger.info(f"Found cookie button with selector: {selector}")
                btn.click()
                time.sleep(0.5)
                return # Clicked one, assume handled
    except:
        pass

class NavigatorMixin:
    """Mixin for navigation and initial form filling logic."""
    
    BASE_URL = "https://www.turkcell.com.tr/yukle/tl-yukle"

    def navigate_to_base_url(self):
        logger.info(f"Navigating to {self.BASE_URL}")
        self.page.goto(self.BASE_URL)
        time.sleep(2) # Wait for banner
        handle_cookies(self.page)

    def select_upload_type(self, upload_type: str = "Package"):
        """
        Selects 'Paket Yükle' or 'TL Yükle'.
        upload_type: "Package" or "TL"
        """
        logger.info(f"Selecting upload type: {upload_type}")
        try:
             target_radio = self.Maps["radio_tl"] if upload_type == "TL" else self.Maps["radio_package"]
             # Wait for radio or label
             self.page.wait_for_selector(target_radio, timeout=10000)
             
             # Click logic... force=True usually works for hidden radios
             self.page.click(target_radio, force=True)
             time.sleep(1)
             
             # Fallback: check if the correct type is actually selected? 
             # Visual check might be hard without screenshots, assuming click worked.
        except Exception as e:
             logger.error(f"Failed to select upload type {upload_type}: {e}")
             # try fallback by text?
             if upload_type == "TL":
                 try:
                     self.page.click('text="TL Yükle"', timeout=2000)
                 except:
                     pass

    def fill_phone(self, phone_number: str):
        logger.info(f"Filling phone number: {phone_number}")
        # Wait for input
        self.page.wait_for_selector(self.Maps["phone_input"])
        
        # Click and Type
        # Click to focus and activate mask
        self.page.click(self.Maps["phone_input"])
        
        # Wait for mask JS to initialize
        time.sleep(0.5)
        
        # Clean number first (remove leading 0 or +90 if present)
        # Also remove leading '5' because the mask is 0(5__) and '5' is pre-filled.
        clean_number = phone_number.replace("+90", "").replace(" ", "").lstrip("0")
        if clean_number.startswith("5"):
            clean_number = clean_number[1:]
        
        logger.info(f"Typing clean number (without prefix): {clean_number}")
        self.page.keyboard.type(clean_number, delay=150) # Slower typing for mask
        
        time.sleep(1)
        
        # Validation
        max_attempts = 2
        for attempt in range(max_attempts):
            # Check value
            input_val = self.page.input_value(self.Maps["phone_input"])
            clean_val = input_val.replace(" ", "").replace("(", "").replace(")", "")
            
            logger.info(f"Input Value: {input_val} (Clean: {clean_val}) - Expected: {clean_number}")
            
            # Check for immediate error
            error_el = self.page.query_selector('.molecule-masked-input_maskedInput__errorText__3q3B7') # Generic error selector guess or specific if known
            if error_el and error_el.is_visible():
                logger.warning(f"Phone Error visible: {error_el.inner_text()}")
            
            if clean_number in clean_val:
                logger.info("Phone number entered correctly.")
                break
            else:
                logger.warning(f"Phone mismatch! Retrying... Attempt {attempt+1}")
                self.page.fill(self.Maps["phone_input"], "") # Clear
                time.sleep(0.5)
        if self.page.input_value(self.Maps["phone_input"]).replace(" ", "").replace("(", "").replace(")", "").endswith(clean_number):
             logger.info("Phone number entered correctly.")
        else:
             logger.error("Failed to verify phone number entry.")

        self.take_screenshot("after_phone_input")
