from .base_operator import BaseOperator
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from ..utils.captcha_solver import CaptchaSolver
import time
import logging

logger = logging.getLogger(__name__)

class TurkcellOperator(BaseOperator):
    BASE_URL = "https://www.turkcell.com.tr/paket-ve-tarifeler/paket-yukle"

    def __init__(self, headless=True):
        self.driver = None
        self.headless = headless
        self.captcha_solver = CaptchaSolver()

    def initialize_driver(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)

    def navigate_to_home(self):
        self.driver.get(self.BASE_URL)
        logger.info("Navigated to Turkcell Payload Page")

    def select_type(self, type_value: str = "Package"):
        """
        type_value: 'Package' or 'TL'
        """
        try:
            selector = f'input[type="radio"][value="{type_value}"]'
            element = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            # Click parent label if input is hidden/covered
            element.find_element(By.XPATH, "./..").click() 
            logger.info(f"Selected type: {type_value}")
        except Exception as e:
            logger.error(f"Failed to select type: {e}")
            raise

    def enter_phone_number(self, phone: str):
        try:
            # Matches 'input.molecule-masked-input...'
            input_el = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.molecule-masked-input_maskedInput__input__QSECa")))
            input_el.click()
            input_el.clear()
            input_el.send_keys(phone)
            logger.info(f"Entered phone number: {phone}")
        except Exception as e:
            logger.error(f"Failed to enter phone: {e}")
            raise

    def solve_captcha(self) -> bool:
        try:
            # 1. Get Image
            img_el = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'img[alt="captcha"]')))
            img_src = img_el.get_attribute("src")
            
            # 2. Solve
            code = self.captcha_solver.solve_base64(img_src)
            logger.info(f"Solved Captcha: {code}")

            # 3. Enter Code
            # Selector from map: input.atom-input_a-trkclAppInputWrapper__input__lGLNB
            input_selector = "input[maxlength='6']"
            input_el = self.driver.find_element(By.CSS_SELECTOR, input_selector)
            input_el.clear()
            input_el.send_keys(code)

            # 4. Click Submit
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button.captcha_a-trkclAppCaptchaWrapper__captchaControl--captchaButton__l8YJ_")
            submit_btn.click()
            
            # 5. Wait for validation (check if error appears or if we moved to next step)
            # This part might need adjustment based on real behavior (e.g. check for 'error' class)
            time.sleep(2) 
            return True
        except Exception as e:
            logger.error(f"Captcha failed: {e}")
            return False

    def select_package(self, package_name: str):
        try:
            # 1. Click 'EK PAKETLER' tab (or other logic if needed)
            # Using generic wait for tab content
            tab = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="EK PAKETLER"]')))
            tab.click()
            time.sleep(1) # Wait for animation

            # 2. Find package by name
            # Iterate through cards
            cards = self.driver.find_elements(By.CSS_SELECTOR, "a.molecule-dynamic-card_linkDecoration__cDpXS")
            found = False
            for card in cards:
                title_el = card.find_element(By.CSS_SELECTOR, "p.molecule-dynamic-card_m-trkclDynamicCard__flat--header--title__VSjLt")
                if package_name.lower() in title_el.text.lower():
                    card.click()
                    found = True
                    logger.info(f"Selected package: {package_name}")
                    break
            
            if not found:
                raise Exception(f"Package {package_name} not found")

            # 3. Click 'Devam Et'
            continue_btn = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.molecule-basket-amount-bar_basket-amount-bar__button__Zg8N5")))
            continue_btn.click()
            logger.info("Clicked Continue")

        except Exception as e:
            logger.error(f"Failed to select package: {e}")
            raise

    def fill_payment_info(self, card_info: dict):
        try:
            # Name
            self.wait.until(EC.presence_of_element_located((By.NAME, "cardHolder"))).send_keys(card_info['holder_name'])
            
            # Number
            self.driver.find_element(By.NAME, "cardNumber").send_keys(card_info['number'])
            
            # Month
            # Note: This is a custom select or native select. Element map says select[data-testid="Ay"]
            # But Ant Design often hides the real select. 
            # If native select is available/visible:
            self.driver.find_element(By.XPATH, f"//select[@data-testid='Ay']/option[@value='{card_info['month']}']").click()
            
            # Year
            self.driver.find_element(By.XPATH, f"//select[@data-testid='Yıl']/option[@value='{card_info['year']}']").click()
            
            # CVV
            self.driver.find_element(By.NAME, "ccv").send_keys(card_info['cvv'])
            
            # Agreement Checkbox
            checkbox = self.driver.find_element(By.CSS_SELECTOR, "input.ant-checkbox-input[type='checkbox']")
            if not checkbox.is_selected():
                # Click the wrapper label as input might be hidden
                checkbox.find_element(By.XPATH, "./..").click()

            # Submit 'İşlemi Tamamla'
            # Selector from map: button.atom-button_a-trkclAppBtn__secondary--light__oqDeQ
            submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'İşlemi Tamamla')]")
            submit_btn.click()
            logger.info("Submitted payment info")

        except Exception as e:
            logger.error(f"Payment failed: {e}")
            raise

    def handle_3d_secure(self) -> bool:
        try:
            # Wait for iframe wrapper
            wrapper = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".Iframe_iframe-wrapper--open__tLv_K")))
            
            # Switch to frame
            self.driver.switch_to.frame("three-d-iframe")
            logger.info("Switched to 3D Secure Iframe")
            
            # Logic here depends on bank. 
            # For now we return True indicating we reached this step.
            return True
            
        except Exception as e:
            logger.error(f"3D Secure handling failed: {e}")
            return False

    def close(self):
        if self.driver:
            self.driver.quit()
