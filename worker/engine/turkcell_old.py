
import time
import base64
import logging
import re
import json
import random
from datetime import datetime
from django.utils import timezone
from core.models import SMSLog
from typing import Dict, Optional
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .base_operator import BaseOperator
from worker.utils.captcha_solver import CaptchaSolver

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

class TurkcellOperator(BaseOperator):
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
            "package_name": '[class*="header--title"]',
            "continue_btn": 'button[class*="basket-amount-bar__button"]',
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
        import os
        import glob
        try:
            files = glob.glob('debug_output/*')
            for f in files:
                os.remove(f)
            logger.info("Cleared debug_output directory.")
        except Exception as e:
            logger.warning(f"Failed to clear debug_output: {e}")

    def navigate_to_base_url(self):
        logger.info(f"Navigating to {self.BASE_URL}")
        self.page.goto(self.BASE_URL)

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
    
    def solve_captcha(self) -> bool:
        logger.info("Function: solve_captcha")
        self.take_screenshot("before_captcha_check")
        try:
            max_retries = 3
            for attempt in range(max_retries):
                logger.info(f"Captcha attempt {attempt + 1}/{max_retries}")
                
                # Check if captcha exists (Wait for it to appear)
                try:
                    self.page.wait_for_selector(self.Maps["captcha_img"], state="visible", timeout=5000)
                except Exception:
                    logger.info("Captcha image not visible after wait, assuming solved or not present.")
                    return True

                # Get Image Source (Base64)
                img_element = self.page.query_selector(self.Maps["captcha_img"])
                if not img_element:
                     logger.error("Captcha element missing during attempt.")
                     return False
                     
                src = img_element.get_attribute("src")
                if not src:
                    logger.error("Captcha source empty.")
                    return False
                
                logger.info(f"Captcha Src (first 30 chars): {src[:30]}")

                # Solve
                try:
                    code = self.captcha_solver.solve_base64(src)
                    logger.info(f"Solved Captcha: {code}")
                    
                    # Validation: Captcha should be 6 chars usually for this site
                    if len(code) < 5:
                        logger.warning(f"Solved code '{code}' is too short. Refreshing...")
                        self.page.click(self.Maps["captcha_refresh"])
                        self.page.wait_for_timeout(1500) # Wait for new image
                        continue
                        
                except Exception as e:
                    logger.error(f"DDDDOCR Failed: {e}")
                    return False
                
                # Fill
                # Click to focus first
                self.page.click(self.Maps["captcha_input"])
                time.sleep(0.2)
                
                # Type character by character to trigger React/JS events
                logger.info(f"Typing captcha code: {code}")
                for char in code:
                    self.page.keyboard.type(char, delay=100) 
                
                # Press Enter or Tab to blur/commit
                self.page.keyboard.press("Tab")
                time.sleep(0.5)
                
                # Press Enter or Tab to blur/commit
                self.page.keyboard.press("Tab")
                time.sleep(0.5)

                # Click Submit
                submit_btn = self.page.query_selector(self.Maps["captcha_submit"])
                if submit_btn:
                    if not submit_btn.is_enabled():
                        logger.warning("Submit button disabled! Waiting...")
                        self.page.wait_for_function(f"document.querySelector('{self.Maps['captcha_submit']}').disabled == false", timeout=3000)
                    
                    try:
                        submit_btn.click()
                        logger.info("Clicked captcha submit button.")
                    except Exception as e:
                        logger.error(f"Failed to click submit button: {e}")
                else:
                    logger.error(f"Submit button not found with selector: {self.Maps['captcha_submit']}")
                    # Dump HTML to see what's wrong
                    with open(f"debug_output/captcha_submit_missing_{attempt}.html", "w") as f:
                        f.write(self.page.content())
                    self.take_screenshot(f"captcha_submit_missing_{attempt}")
                    return False
                
                # Check result
                try:
                    # Wait a bit for processing (User said packages come later)
                    # Wait a bit for processing (User said packages come later)
                    logger.info("Waiting 15s for page transition...")
                    self.page.wait_for_timeout(10000)
                    
                    # Success check: Next step visible
                    if self.page.is_visible(self.Maps["tab_ek_paketler"]):
                        logger.info("Captcha successful (Next step visible)")
                        return True
                        
                    # Error check: Input still visible + Error message?
                    error_el = self.page.query_selector('.atom-input-message_inputMessage__text__error__jF1_D')
                    if error_el and error_el.is_visible():
                         logger.warning(f"Captcha Error: {error_el.inner_text()}. Retrying...")
                         self.take_screenshot(f"captcha_error_attempt_{attempt}")
                         self.page.click(self.Maps["captcha_refresh"])
                         self.page.wait_for_timeout(1500)
                         continue
                    
                    # Check for "Invalid Number" Modal (e.g. "Girmiş olduğunuz numara Turkcell’den hizmet almamaktadır.")
                    # Selector guess based on screenshot: .ant-modal-content or similar
                    try:
                        modal_text_el = self.page.query_selector('.ant-modal-body')
                        if modal_text_el and modal_text_el.is_visible():
                            text = modal_text_el.inner_text()
                            if "hizmet almamaktadır" in text or "Türk Telekom" in text or "Vodafone" in text:
                                logger.error(f"Invalid Phone Number Error: {text}")
                                self.take_screenshot("invalid_number_modal")
                                return False # Stop retrying, this is a fatal error for this number
                    except Exception:
                        pass
                         
                    # Fallback check
                    if self.page.is_hidden(self.Maps["captcha_input"]):
                         logger.info("Captcha successful (Input hidden)")
                         return True
                    
                    # If we are here, it means we are still on the page, input is visible, 
                    # but no specific error was found. Treat as failure and retry.
                    logger.warning("Captcha kabul edilmedi veya hata mesajı algılanamadı. Tekrar deneniyor...")
                    self.take_screenshot(f"captcha_unknown_state_attempt_{attempt}")
                    self.page.click(self.Maps["captcha_refresh"])
                    self.page.wait_for_timeout(2000)
                    continue
                         
                except Exception as e:
                    logger.error(f"Error checking captcha result: {e}")
                    self.take_screenshot(f"captcha_check_error_{attempt}")
                    # If check failed, try refreshing anyway to be safe
                    try:
                        self.page.click(self.Maps["captcha_refresh"])
                        self.page.wait_for_timeout(2000)
                    except:
                        pass
            
            logger.error("Max captcha retries exceeded.")
            logger.error("CAPTCHA_RETRY_LIMIT_EXCEEDED") # Frontend detection key
            self.take_screenshot("captcha_failed_final")
            return False
                
        except Exception as e:
            logger.error(f"Fatal Error in solve_captcha: {e}")
            self.take_screenshot("captcha_fatal_error")
            return False

    def take_screenshot(self, name: str):
        try:
            path = f"debug_output/{name}.png"
            self.page.screenshot(path=path)
            logger.info(f"Screenshot saved: {path}")
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")

    def scrape_packages(self) -> list:
        logger.info("Scraping packages...")
        self.take_screenshot("scraping_start")
        packages = []
        
        try:
            # Wait for content to load
            try:
                self.page.wait_for_selector(self.Maps["tab_ek_paketler"], timeout=20000)
            except Exception:
                logger.error("Timeout waiting for packages tab.")
                return []
                
            # Find all tabs
            # Selector for tabs: .molecule-tab_m-trkclAppTab__taAs5 .molecule-tab_m-tabItem__Ee3sA
            # We need to click each and scrape
            
            # Using evaluate to get clean text and structure might be easier, 
            # but let's stick to playwright interactions for reliability
            
            # Selector for tabs: .molecule-tab_m-trkclAppTab__taAs5 .molecule-tab_m-tabItem__Ee3sA
            # We need to click each and scrape
            
            # Using broader selectors as class names seem to be hashed/dynamic
            # Look for elements that *contain* the class prefix or structure
            
            # Tab Container: class starting with "molecule-tab"
            # Tabs: inside container, div with title attribute?
            
            # Try to find the tab container more robustly
            try:
                # Wait for any tab element to appear
                self.page.wait_for_selector('div[class*="molecule-tab"]', timeout=20000)
            except:
                logger.error("Timeout waiting for tabs.")
                return []
                
            # Query all divs that look like tabs (width title usually) inside the main wrapper
            # The structure is: Wrapper -> Tab List -> Tab Item
            
            # Let's try to get all elements with class containing 'tabItem'
            tabs = self.page.query_selector_all('div[class*="tabItem"]')
            
            if not tabs:
                 # Fallback: try finding by titles directly?
                 logger.warning("No elements with 'tabItem' class found. Trying generic approach.")
                 tabs = self.page.query_selector_all('div[role="tab"]')
            
            logger.info(f"Found {len(tabs)} category tabs.")
            
            if len(tabs) == 0:
                logger.error("No tabs found! Dumping HTML...")
                with open("debug_output/no_tabs_debug.html", "w") as f:
                    f.write(self.page.content())
                self.take_screenshot("no_tabs_found")
            
            for i, tab in enumerate(tabs):
                try:
                    category_name = (
                        tab.get_attribute('title') 
                        or tab.inner_text().strip() 
                        or tab.get_attribute('aria-label')
                        or tab.get_attribute('data-label')
                        or ""
                    ).strip()
                    if not category_name:
                        category_name = f"Kategori {i+1}"
                        logger.warning(f"Tab {i} has no readable name, using fallback: {category_name}")
                        
                    logger.info(f"Processing Category: {category_name}")
                    
                    # Click tab
                    try:
                        tab.click()
                        time.sleep(3) # Wait for cards to switch - INCREASED WAIT
                    except Exception as e:
                        logger.warning(f"Could not click tab {category_name}: {e}")
                        continue
                        
                    # Check for "Tümünü Gör" (See All) button and click it if present
                    try:
                        see_all_btn = self.page.query_selector('button:has-text("Tümünü Gör")')
                        if see_all_btn and see_all_btn.is_visible():
                            logger.info("Found 'Tümünü Gör' button. Clicking...")
                            see_all_btn.click()
                            time.sleep(3) # Wait for expansion
                    except Exception as e:
                        logger.warning(f"Error checking/clicking 'Tümünü Gör': {e}")

                    # Dump full page content for debugging correct selectors
                    if i == 0:
                        with open("debug_output/full_packages_page.html", "w") as f:
                            f.write(self.page.content())

                    # Scrape cards in this view
                    # Use the same selector as select_package (the <a> wrapper)
                    card_selector = self.Maps["package_card"]  # 'a[class*="molecule-dynamic-card_linkDecoration"]'
                    try:
                        self.page.wait_for_selector(card_selector, timeout=5000)
                    except:
                        logger.warning(f"No package cards found in {category_name}. Skipping.")
                        continue

                    cards = self.page.query_selector_all(card_selector)
                    
                    logger.info(f"Found {len(cards)} package cards in {category_name}")
                    
                    if len(cards) == 0:
                         with open(f"debug_output/no_cards_{i}.html", "w") as f:
                            f.write(self.page.content())
                         self.take_screenshot(f"no_cards_{i}")
                    
                    for idx, card in enumerate(cards):
                        try:
                            # Name Extraction
                            name = "Unknown"
                            name_el = card.query_selector(self.Maps["package_name"])  # '[class*="header--title"]'
                            if name_el:
                                text = name_el.inner_text().strip()
                                if text:
                                    name = text
                            
                            # Price Extraction
                            price = 0.0
                            price_text = ""
                            price_el = card.query_selector('[class*="priceInfoText"]')
                            if price_el:
                                price_text = price_el.inner_text().strip()
                            
                            # Parse price (e.g., "1250 TL/4 HAFTA")
                            if price_text:
                                price_match = re.search(r'(\d+[.,]?\d*)', price_text)
                                if price_match:
                                    try:
                                        price = float(price_match.group(1).replace(',', '.'))
                                    except:
                                        pass
                            
                            # Debug if extraction failed
                            if name == "Unknown" or price == 0.0:
                                if idx < 3:
                                    with open(f"debug_output/card_fail_{i}_{idx}.html", "w") as f:
                                        f.write(card.inner_html())
                                
                            # Only add if we have both name and price
                            if name != "Unknown" and price > 0:
                                logger.info(f"Scraped: {name} - {price} TL")
                                packages.append({
                                    'category': category_name,
                                    'name': name,
                                    'package_id': name,
                                    'price': price
                                })
                            else:
                                 pass
                            
                        except Exception as e:
                            logger.warning(f"Error scraping a card: {e}")
                            
                except Exception as e:
                    logger.error(f"Error processing tab {i}: {e}")
                    
            return packages

        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            return []

    def _match_package(self, package_id: str, title_text: str) -> bool:
        """Check if package_id matches title_text using multiple strategies."""
        # 1. Exact match
        if package_id == title_text:
            return True
        # 2. Contains match (either direction)
        if package_id in title_text or title_text in package_id:
            return True
        # 3. Clean match (remove spaces/case)
        if package_id.lower().replace(" ", "") in title_text.lower().replace(" ", ""):
            return True
        if title_text.lower().replace(" ", "") in package_id.lower().replace(" ", ""):
            return True
        return False

    def _click_and_confirm_package(self, target_card, package_id: str) -> bool:
        """Click the found package card and proceed to continue."""
        logger.info(f"Found package card for {package_id}")
        
        # Strategy: Click the inner div container to avoid 'href' issues on <a> tag
        inner_div = target_card.query_selector('div')
        click_target = inner_div if inner_div else target_card
        
        # Click
        click_target.click()
        logger.info("Clicked package card (inner div)")
        
        # Verify Selection
        time.sleep(1)
        try:
            box_classes = click_target.get_attribute("class")
            if box_classes and "isSelected" in box_classes:
                 logger.info("Selection verified (class check).")
            else:
                 logger.warning(f"Selection might have failed. Classes: {box_classes}. Retrying click with force...")
                 click_target.click(force=True)
                 time.sleep(1)
        except Exception as e:
             logger.warning(f"Verification error: {e}")

        self.take_screenshot("after_card_click")
        
        # Click continue
        time.sleep(1)
        try:
            handle_cookies(self.page)
            self.take_screenshot("before_continue_click")
            
            btn = self.page.query_selector(self.Maps["continue_btn"])
            if btn:
                btn.scroll_into_view_if_needed()
                if btn.is_disabled():
                    logger.warning("Continue button is disabled!")
                else:
                    try:
                        btn.click(timeout=2000)
                        logger.info("Clicked Continue button (standard)")
                    except:
                        logger.info("Standard click failed, trying JS click")
                        self.page.evaluate("arguments[0].click();", btn)
                        logger.info("Clicked Continue button (JS)")
            else:
                logger.error("Continue button not found!")
                
            # Check for accidental Login redirect
            self.page.wait_for_timeout(2000)
            if "giris" in self.page.url or "login" in self.page.url:
                 logger.error("Redirected to Login Page! Attempting to go back or handle.")
                 self.take_screenshot("login_redirect_error")
                 
        except Exception as e:
            logger.error(f"Error clicking continue: {e}")
            
        return True

    def select_package(self, package_id: str = None, amount: float = None) -> bool:
        logger.info(f"Selecting Package: {package_id} or Amount: {amount}")
        self.take_screenshot("package_selection_start")
        try:
            # Wait for package selection screen or tabs
            self.page.wait_for_selector(self.Maps["tab_ek_paketler"], timeout=10000)
            
            if amount:
                pass 
                
            if package_id:
                # Discover ALL category tabs (same logic as scrape_packages)
                try:
                    self.page.wait_for_selector('div[class*="molecule-tab"]', timeout=20000)
                except:
                    logger.error("Timeout waiting for tabs.")
                    return False

                tabs = self.page.query_selector_all('div[class*="tabItem"]')
                if not tabs:
                    tabs = self.page.query_selector_all('div[role="tab"]')
                
                logger.info(f"Found {len(tabs)} category tabs to search.")

                # Iterate through ALL tabs to find the package
                for tab_idx, tab in enumerate(tabs):
                    try:
                        category_name = (
                            tab.get_attribute('title') 
                            or tab.inner_text().strip() 
                            or tab.get_attribute('aria-label')
                            or f"Kategori {tab_idx+1}"
                        ).strip()
                        
                        logger.info(f"Searching in tab: {category_name}")
                        
                        # Click tab
                        try:
                            tab.click()
                            time.sleep(3)
                        except Exception as e:
                            logger.warning(f"Could not click tab {category_name}: {e}")
                            continue

                        # Check for "Tümünü Gör" button
                        try:
                            see_all_btn = self.page.query_selector('button:has-text("Tümünü Gör")')
                            if see_all_btn and see_all_btn.is_visible():
                                logger.info("Found 'Tümünü Gör' button. Clicking...")
                                see_all_btn.click()
                                time.sleep(3)
                        except Exception:
                            pass

                        # Find package cards in this tab
                        try:
                            self.page.wait_for_selector(self.Maps["package_card"], timeout=5000)
                        except Exception:
                            logger.warning(f"No package cards in tab {category_name}")
                            continue

                        cards = self.page.query_selector_all(self.Maps["package_card"])
                        logger.info(f"Found {len(cards)} package cards in {category_name}.")
                        
                        for i, card in enumerate(cards):
                            title_el = card.query_selector(self.Maps["package_name"])
                            if title_el:
                                title_text = title_el.inner_text().strip()
                                logger.info(f"  Card {i} Title: {title_text}")
                                
                                if self._match_package(package_id, title_text):
                                    logger.info(f"✅ Match found in tab '{category_name}': {title_text}")
                                    with open("debug_output/packages_page.html", "w") as f:
                                        f.write(self.page.content())
                                    return self._click_and_confirm_package(card, package_id)
                            else:
                                logger.warning(f"  Card {i} has no title element.")
                                
                    except Exception as e:
                        logger.error(f"Error searching tab {tab_idx}: {e}")
                        continue

                # If we get here, package was not found in any tab
                logger.error(f"Package '{package_id}' not found in any of {len(tabs)} tabs.")
                with open("debug_output/packages_page.html", "w") as f:
                    f.write(self.page.content())
                self.take_screenshot("package_not_found_all_tabs")
                return False

            return False
        except Exception as e:
            logger.error(f"Error selecting package: {e}")
            return False

    def process_payment(self) -> bool:
        if not self.card:
            logger.error("No credit card provided to operator")
            return False
            
        logger.info("Processing Payment")
        try:
            # Wait for Payment Page
            self.page.wait_for_selector(self.Maps["card_holder"], timeout=15000)
            
            # User requested screenshot of payment page
            self.take_screenshot("payment_page_loaded")
            
            # Fill Details
            self.page.fill(self.Maps["card_holder"], self.card.holder_name)
            self.page.fill(self.Maps["card_number"], self.card.card_number)
            
            # Expiry
            # Ensure correct format (MM and YYYY)
            try:
                # Month: Ensure 2 digits (e.g. "1" -> "01")
                month_val = str(self.card.exp_month).strip()
                if len(month_val) == 1:
                    month_val = f"0{month_val}"
                
                # Year: Ensure 4 digits (e.g. "26" -> "2026")
                year_val = str(self.card.exp_year).strip()
                if len(year_val) == 2:
                    year_val = f"20{year_val}"
                
                logger.info(f"Selecting expiry: {month_val}/{year_val}")
                
                 # Try 1: Standard Select
                try:
                    self.page.select_option(self.Maps["exp_month"], value=month_val)
                    self.page.select_option(self.Maps["exp_year"], value=year_val)
                except:
                    pass

                # Try 2: Force JS Update (Best for hidden native selects)
                # Dispatch events to notify React/Angular
                # Note: evaluate passes the second argument as a single object/list to the function.
                js_script = """
                ([selector, value]) => {
                    const el = document.querySelector(selector);
                    if (el) {
                        el.value = value;
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        return true;
                    }
                    return false;
                }
                """
                self.page.evaluate(js_script, [self.Maps["exp_month"], month_val])
                self.page.evaluate(js_script, [self.Maps["exp_year"], year_val])
                
                logger.info("Expiry selection executed via JS")
                
            except Exception as e:
                logger.warning(f"Expiry selection failed: {e}")

            # CVV
            # Map says input[name="ccv"]
            self.page.fill('input[name="ccv"]', self.card.cvv)
            
            # Agreement
            try:
                # User warned that clicking text opens a modal. verification: check the checkbox wrapper directly.
                # Selector from user snippet: .ant-checkbox-wrapper
                # We can also try to force check the input
                
                checkbox_wrapper = self.page.query_selector('.ant-checkbox-wrapper')
                if checkbox_wrapper:
                    # Check if already checked
                    if "ant-checkbox-wrapper-checked" not in checkbox_wrapper.get_attribute("class"):
                        checkbox_wrapper.click()
                        logger.info("Clicked agreement checkbox wrapper")
                    else:
                        logger.info("Agreement checkbox already checked")
                else:
                    # Fallback
                    self.page.check('input[type="checkbox"]')
                    logger.info("Checked agreement checkbox input")
                    
            except Exception as e:
                logger.warning(f"Agreement checkbox click failed: {e}. Trying generic checkbox.")
                # Fallback
                self.page.click('input[type="checkbox"]')

            # Submit
            # Wait for button to be enabled (it might be disabled until checkbox is checked)
            self.page.wait_for_selector(self.Maps["submit_payment"], state="visible")
            time.sleep(1) # Give it a moment to become enabled
            
            submit_btn = self.page.locator(self.Maps["submit_payment"])
            if submit_btn.is_disabled():
                 logger.warning("Submit button is disabled! Checkbox might not be checked.")
                 # Try forcing checkbox again
                 self.page.click('.ant-checkbox-wrapper') 
                 time.sleep(0.5)
            
            # Double check enabling
            if submit_btn.is_disabled():
                 logger.error("Submit button still disabled despite retry. Attempting JS click anyway.")
            
            # Click and verify
            logger.info("Clicking 'İşlemi Tamamla' button...")
            
            # 1. Try standard click
            try:
                submit_btn.click(timeout=3000)
            except Exception as e:
                logger.warning(f"Standard click failed: {e}. Trying JS click.")
                self.page.evaluate("arguments[0].click();", submit_btn.element_handle())
            
            # 2. Validation: Did we move to 3D secure or is there a loading indicator?
            # Wait for potential loader or iframe or disappearance of button
            time.sleep(2)
            
            # Check for error on payment page
            error_el = self.page.query_selector('.ant-form-item-explain-error')
            if error_el and error_el.is_visible():
                logger.error(f"Payment Form Error: {error_el.inner_text()}")
                self.take_screenshot("payment_form_error")
                return False

            logger.info("Payment submission clicked. Proceeding to 3D Secure check.")
            
            return True
            
        except Exception as e:
            logger.error(f"Payment failed: {e}")
            self.take_screenshot("payment_page_failed")
            return False


    def _submit_sms_code(self, iframe_selector, code) -> (bool, str):
        """
        Helper to enter SMS code into the 3D secure iframe and submit.
        """
        try:
            # Re-acquire iframe with retries (it may take a moment to be ready)
            frame = None
            for retry in range(3):
                frame_element = self.page.query_selector(iframe_selector)
                if frame_element:
                    frame = frame_element.content_frame()
                    if frame:
                        break
                logger.warning(f"Iframe not ready, retry {retry+1}/3...")
                time.sleep(2)
            
            if not frame:
                return False, "Iframe not accessible after retries"
                 
            logger.info(f"Submitting code: {code}")
            
            # Find Input
            input_selectors = [
                'input[name="hasMasked"]',        # IstanbulKart/PayCell specific
                'input[name="otpCode"]', 
                'input[name="code"]',
                'input[id="code"]',
                'input.password-input',
                'input[type="tel"]',
                'input[type="number"]',
                'input[type="password"]', 
                'input[type="text"][maxlength="6"]',
                'input[name="password"]',
                'input[id*="sms"]',
                'input[id*="code"]'
            ]
            
            input_el = None
            for sel in input_selectors:
                input_el = frame.query_selector(sel)
                if input_el:
                    logger.info(f"Found input with selector: {sel}")
                    break
            
            # Smart Fallback: If no specific selector matched, look for ANY single visible input
            if not input_el:
                logger.info("Specific input selectors failed. Trying smart fallback...")
                try:
                    # Find all inputs that are NOT hidden/submit/checkbox/radio/button/image
                    all_inputs = frame.query_selector_all('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="image"]):not([type="checkbox"]):not([type="radio"])')
                    
                    visible_inputs = []
                    for inp in all_inputs:
                        try:
                            if inp.is_visible() and inp.is_editable():
                                visible_inputs.append(inp)
                        except:
                            pass
                    
                    if len(visible_inputs) == 1:
                        input_el = visible_inputs[0]
                        logger.info("Smart Fallback: Found exactly one visible input. Using it.")
                    elif len(visible_inputs) > 1:
                        logger.warning(f"Smart Fallback Failed: Found {len(visible_inputs)} visible inputs. Ambiguous.")
                        # Log attributes for debugging
                        for i, inp in enumerate(visible_inputs):
                            try:
                                logger.info(f"  Input {i}: name={inp.get_attribute('name')}, id={inp.get_attribute('id')}, type={inp.get_attribute('type')}")
                            except:
                                pass
                except Exception as e:
                    logger.error(f"Smart fallback error: {e}")

            if input_el:
                # Use type instead of fill to simulate human typing and trigger key events
                input_el.click()
                input_el.type(code, delay=100)
                logger.info("Typed SMS code.")
                self.take_screenshot("3d_secure_code_filled")
                
                submit_selectors = [
                    '#btn-commit',                    # IstanbulKart/PayCell specific
                    '#DevamEt',                       # Specific ID provided by user
                    'input[name="DevamEt"]',          # Specific Name provided by user
                    'button:has-text("Devam")',
                    'input[type="submit"]',
                    'button[type="submit"]',
                    'button:has-text("Gönder")',
                    'button:has-text("Onayla")',
                    'button:has-text("Submit")'
                ]
                
                submit_btn = None
                for sel in submit_selectors:
                    submit_btn = frame.query_selector(sel)
                    if submit_btn:
                        # Check visibility
                        if submit_btn.is_visible():
                            break
                        else:
                            submit_btn = None # Ignore hidden buttons
                
                if submit_btn:
                    logger.info(f"Found submit button. Clicking...")
                    try:
                        # Try standard click first with short timeout
                        submit_btn.click(timeout=3000)
                    except Exception as e:
                        logger.warning(f"Standard click failed ({e}). Trying JS click.")
                        frame.evaluate("arguments[0].click();", submit_btn)
                    
                    logger.info("Clicked Submit/Continue.")
                    
                    logger.info("Waiting for transaction processing (polling)...")
                    
                    # Poll for result instead of blind sleep
                    poll_start = time.time()
                    poll_timeout = 60  # max 60 seconds
                    
                    while time.time() - poll_start < poll_timeout:
                        self.take_screenshot(f"3d_secure_poll_{int(time.time()-poll_start)}")
                        
                        # Check 1 & 2: iframe/wrapper gone = bank processed, back to main page
                        iframe_still = self.page.query_selector(iframe_selector)
                        wrapper = self.page.query_selector(
                            self.Maps.get("iframe_wrapper", '.Iframe_iframe-wrapper--open__tLv_K')
                        )
                        
                        if not iframe_still and not wrapper:
                            logger.info("3D Secure iframe/wrapper closed. Verifying transaction result on main page...")
                            
                            # Wait for page update/redirect
                            time.sleep(3) 
                            self.take_screenshot("post_3d_secure_check")
                            
                            # Check for Success Indicators
                            # "Siparişiniz Alındı", "Teşekkürler", "İşleminiz başarıyla", "Paket yükleme talebiniz alınmıştır"
                            page_content = self.page.content()
                            
                            success_keywords = [
                                "Siparişiniz Alındı",
                                "Teşekkürler",
                                "başarıyla",
                                "Paket yükleme talebiniz alınmıştır",  # From user screenshot
                                "bilgilendirme yapılacaktır"
                            ]
                            
                            if any(kw in page_content for kw in success_keywords):
                                logger.info("Transaction Verified: SUCCESS")
                                return True, "3D Secure completed and verified success (Success message found)."
                                
                            # Check for Error Indicators
                            # "Hata", "Başarısız", "Reddedildi"
                            # Also check for specific error elements if known
                            if "Hata" in page_content or "Başarısız" in page_content or "Reddedildi" in page_content:
                                logger.error("Transaction Verified: FAILED (Error detected on page)")
                                self.take_screenshot("post_3d_secure_failed")
                                return False, "3D Secure closed but error detected on page."
                                
                            # Ambiguous Case
                            # If we are back on the payment form (e.g. "Kart Numarası" input is visible), it failed silent/softly
                            if self.page.is_visible('input[name="cardNumber"]'):
                                logger.warning("Transaction Verified: FAILED (Returned to payment form)")
                                return False, "Returned to payment form without success message."
                                
                            # Final Default: Assume failure if no positive confirmation
                            logger.warning("Transaction Verified: AMBIGUOUS (No success/error message found). Assuming Failure.")
                            return False, "Ambiguous result after 3D Secure."
                        
                        # Check 3: Try reading iframe content for result keywords
                        try:
                            current_frame = iframe_still.content_frame()
                            if current_frame:
                                body_text = current_frame.inner_text('body', timeout=3000)
                                if any(kw in body_text for kw in ["Başarılı", "Successful", "Onaylandı", "Approved"]):
                                    logger.info(f"3D Secure SUCCESS detected: {body_text[:100]}")
                                    return True, body_text[:200]
                                if any(kw in body_text for kw in ["Başarısız", "Failed", "Reddedildi", "Declined", "Hata"]):
                                    logger.error(f"3D Secure FAILURE detected: {body_text[:100]}")
                                    return False, body_text[:200]
                        except Exception:
                            logger.info("Frame content not accessible, continuing poll...")
                        
                        time.sleep(3)
                    
                    # Final fallback after timeout
                    self.take_screenshot("3d_secure_poll_timeout")
                    
                    # Last check: is iframe still there?
                    if not self.page.query_selector(iframe_selector):
                        return True, "3D Secure completed (iframe gone after poll timeout)"
                    
                    return False, "Timeout: 3D Secure did not complete within poll window"
                else:
                    logger.error("Submit button not found or not visible!")
                    self.take_screenshot("3d_secure_no_submit_btn")
                    return False, "Submit button not found"
            else:
                return False, "Input field for code not found"
        except Exception as e:
            logger.error(f"Error in _submit_sms_code: {e}")
            return False, str(e)

    def handle_3d_secure(self) -> (bool, str):
        logger.info("Handling 3D Secure")
        try:
            # Ensure cookies are accepted before waiting for iframe (might block view)
            handle_cookies(self.page)
            
            # 3D Secure usually loads in an iframe.
            # Sometimes it takes a while for the bank to redirect.
            
            # Use a polling loop to wait for the iframe without throwing immediate timeout errors
            timeout_seconds = 300  # Wait up to 5 minutes
            start_time = time.time()
            # Track when we started waiting for 3DS to filter old SMS
            process_start_time = timezone.now()
            
            iframe_wrapper_selector = self.Maps.get("iframe_wrapper", '.Iframe_iframe-wrapper--open__tLv_K')
            iframe_name = self.Maps.get("iframe_name", 'three-d-iframe')
            iframe_selector = f'iframe[name="{iframe_name}"]'
            
            logger.info(f"Waiting for 3D Secure iframe (up to {timeout_seconds}s)...")
            
            iframe_found = False
            while time.time() - start_time < timeout_seconds:
                # Check for wrapper
                if self.page.query_selector(iframe_wrapper_selector):
                    logger.info("Iframe wrapper found.")
                    iframe_found = True
                    break
                
                # Check for iframe directly
                if self.page.query_selector(iframe_selector):
                    logger.info("Iframe element found directly.")
                    iframe_found = True
                    break
                
                # Log waiting status every 5 seconds
                if int(time.time() - start_time) % 5 == 0:
                    logger.info(f"Waiting for 3D Secure iframe... ({int(time.time() - start_time)}s passed)")
                
                time.sleep(1)
            
            if not iframe_found:
                 logger.error("Timeout: 3D Secure iframe not found after waiting.")
                 self.take_screenshot("3d_secure_timeout")
                 return False, "Timeout waiting for 3D Secure Iframe"

            # Get frame
            frame_element = self.page.query_selector(iframe_selector)
            if frame_element:
                frame = frame_element.content_frame()
                if frame:
                    logger.info("Switched to 3D Secure Frame")
                    
                    # 3. Wait for content in the frame
                    # We need to ensure the bank page actually loaded inside.
                    try:
                        # Wait for ANY text or body to be populated
                        frame.wait_for_selector('body', timeout=30000)
                        
                        # Loop to wait for specific "SMS" or "Code" input/text
                        # Banks are different, but usually ask for "SMS şifresi" or have a numeric input.
                        
                        sms_wait_timeout = 300 # Wait another 5 mins inside the frame if needed
                        sms_start_time = time.time()
                        
                        logger.info("Waiting for SMS Code Entry Screen...")
                        
                        code_entered = False
                        
                        while time.time() - sms_start_time < sms_wait_timeout:
                            content = frame.content()
                            
                            # Check for common keywords indicating code entry screen
                            # "Doğrulama", "Şifre", "SMS", "Code", "Password"
                            if "SMS" in content or "Şifre" in content or "Doğrulama" in content or "Code" in content:
                                # logger.info("SMS/Password verification keywords found.")
                                
                                # Check Database for new SMS
                                # Look for SMS in the last 3 minutes regardless of when we started
                                lookback_time = timezone.now() - timezone.timedelta(minutes=3)
                                last_sms = SMSLog.objects.filter(received_at__gte=lookback_time).order_by('-received_at').first()
                                
                                if last_sms:
                                    logger.info(f"SMS found in DB (last 3 mins) from {last_sms.sender}: {last_sms.message_content}")
                                    
                                    # Extract Code
                                    match = re.search(r'\b\d{6}\b', last_sms.message_content)
                                    if match:
                                        code = match.group(0)
                                        logger.info(f"Extracted Code: {code}")
                                        return self._submit_sms_code(iframe_selector, code)
                                    else:
                                        logger.warning("SMS found but no 6-digit code extracted.")
                                        # Update process time to avoid reading same bad SMS? 
                                        # Or just wait for next one?
                                
                                # Optional: Check for input field visibility just to log status
                                if not code_entered:
                                     if frame.query_selector('input[type="password"]') or frame.query_selector('input[type="text"]'):
                                         # logger.info("Input field ready, waiting for SMS...")
                                         pass
                            
                            if int(time.time() - sms_start_time) % 5 == 0:
                                logger.info(f"Waiting for SMS... ({int(time.time() - sms_start_time)}s passed)")
                                
                            time.sleep(2) # check DB every 2 seconds
                        
                        logger.warning("SMS Screen timed out (keywords not found). Taking screenshot.")
                        self.take_screenshot("3d_secure_sms_timeout")
                        return False, "Timeout waiting for SMS Screen/Keywords"
                        
                    except Exception as e:
                        logger.error(f"Error waiting for frame content: {e}")
                        self.take_screenshot("3d_secure_frame_empty")
                        return False, f"Frame Content Error: {str(e)}"
            
            logger.error("Iframe found but content_frame() returned None.")
            return False, "Iframe content inaccessible"
            
        except Exception as e:
            logger.error(f"3D Secure Error: {e}")
            logger.error("3D Secure ekranı açılmadı. Ödeme bilgileri hatalı olabilir veya banka reddetti.")
            self.take_screenshot("3d_secure_failed_exception")
            return False, f"Exception: {str(e)}"
