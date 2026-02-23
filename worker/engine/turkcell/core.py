
import logging
import os
import glob
from typing import Dict, Optional
from playwright.sync_api import Page

from worker.engine.base_operator import BaseOperator
from worker.utils.captcha_solver import CaptchaSolver

from .navigator import NavigatorMixin
from .scraper import ScraperMixin
from .payment import PaymentMixin
from .security import SecurityMixin

logger = logging.getLogger(__name__)

class TurkcellOperator(NavigatorMixin, ScraperMixin, PaymentMixin, SecurityMixin, BaseOperator):
    BASE_URL = "https://www.turkcell.com.tr/yukle/tl-yukle"

    @property
    def Maps(self) -> Dict[str, str]:
        return {
            # Step 1: Selection
            "radio_tl": 'input[type="radio"][value="TL"]',
            "radio_package": 'input[type="radio"][value="Package"]',
            
            # Step 2: Phone
            "phone_input": 'input.molecule-masked-input_maskedInput__input__QSECa',
            
            # Step 2.5: Phone Validation Modal (New)
            "invalid_modal_body": '.ant-modal-body',
            
            # Step 3: Captcha
            "captcha_img": 'img[alt="captcha"]',
            "captcha_input": 'input.atom-input_a-trkclAppInputWrapper__input__lGLNB',
            "captcha_submit": 'button.captcha_a-trkclAppCaptchaWrapper__captchaControl--captchaButton__l8YJ_',
            "captcha_refresh": '.captcha_captchaIconWrapper__ZxZ0g', # Refresh icon wrapper
            
            # Step 4: Packages
            "tab_ek_paketler": 'div[title="EK PAKETLER"]',
            "package_card": 'a[class*="molecule-dynamic-card_linkDecoration"]',
            "tl_card": 'div[class*="atom-price-box"]',
            "package_name": '[class*="header--title"]',
            "continue_btn": 'button:has-text("Devam Et")',
            "amount_radio": 'input[name="amount"]',
            
            # Step 5: Payment
            "card_holder": 'input[name="cardHolder"]',
            "card_number": 'input[name="cardNumber"]',
            "exp_month": 'select[data-testid="Ay"]',
            "exp_year": 'select[data-testid="Yıl"]',
            "cvv": 'input[name="cvc"]', # Map says 'ccv' but standard is usually 'cvv' or 'cvc'. HTML Step 5 check needed.
            # Map says: input[name="ccv"]
            "agreement_checkbox": 'input.ant-checkbox-input[type="checkbox"]',
            "submit_payment": 'button:has-text("İşlemi Tamamla")',
            
            # Step 6: 3D Secure
            "iframe_wrapper": '.Iframe_iframe-wrapper--open__tLv_K',
            "iframe_name": 'three-d-iframe'
        }

    def __init__(self, page: Page, card=None):
        super().__init__(page, card)
        self.captcha_solver = CaptchaSolver()
        self.cleanup_debug_output()

    def cleanup_debug_output(self):
        """Clears the debug_output directory."""
        try:
            files = glob.glob('debug_output/*')
            for f in files:
                os.remove(f)
            logger.info("Cleared debug_output directory.")
        except Exception as e:
            logger.warning(f"Failed to clear debug_output: {e}")

    def take_screenshot(self, name: str):
        try:
            path = f"debug_output/{name}.png"
            self.page.screenshot(path=path)
            logger.info(f"Screenshot saved: {path}")
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
