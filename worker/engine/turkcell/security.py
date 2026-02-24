
import time
import re
import logging
from django.utils import timezone
from core.models import SMSLog
from .navigator import handle_cookies

logger = logging.getLogger(__name__)

class SecurityMixin:
    """Mixin for security-related logic (Captcha, 3D Secure, SMS)."""

    def solve_captcha(self, log_callback=None) -> bool:
        logger.info("Function: solve_captcha")
        self.take_screenshot("before_captcha_check")
        try:
            max_retries = 6
            for attempt in range(max_retries):
                if attempt == 3:
                     logger.info("Phase 2 reached: 3 failed attempts, starting next 3...")
                     if log_callback:
                         log_callback("CAPTCHA_PHASE_2")
                         
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
                    logger.info("Waiting up to 15s for page transition (Captcha input hidden)...")
                    try:
                        self.page.wait_for_selector(self.Maps["captcha_input"], state="hidden", timeout=15000)
                    except Exception:
                        logger.warning("Captcha input not hidden within 15s, continuing checks.")
                        self.page.wait_for_timeout(2000)
                    
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

    def _submit_sms_code(self, iframe_selector, code, log_callback=None) -> (bool, str):
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
                else:
                    logger.warning("No submit button found by selectors. Attempting to press 'Enter' on the input field itself...")
                    try:
                        input_el.press("Enter")
                        logger.info("Pressed 'Enter' on SMS input field.")
                    except Exception as e:
                        logger.error(f"Failed to press 'Enter' on input field: {e}")
                        self.take_screenshot("3d_secure_no_submit_btn")
                        return False, "Submit button not found and Enter key failed"
                    
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
                            
                            # Check for Insufficient Limit specifically to fail fast
                            if "limit" in body_text.lower() and ("yetersiz" in body_text.lower() or "yeterli değil" in body_text.lower()):
                                 logger.error(f"3D Secure FAILURE: Insufficient Limit detected inside iframe.")
                                 if log_callback:
                                     log_callback("3DS_ERROR_LIMIT")
                                 return False, "Yetersiz Bakiye/Limit Hatası"

                            if any(kw in body_text for kw in ["Başarısız", "Failed", "Reddedildi", "Declined", "Hata"]):
                                logger.error(f"3D Secure FAILURE detected: {body_text[:100]}")
                                return False, body_text[:200]
                    except Exception:
                        logger.info("Frame content not accessible, continuing poll...")
                    
                    # Check for Error Modal on Main Page (outside iframe)
                    # User provided HTML: .ant-modal .ErrorModal_error-modal__description__7pBeI
                    try:
                        error_modal = self.page.query_selector('.ant-modal-body')
                        if error_modal and error_modal.is_visible():
                            modal_text = error_modal.inner_text().strip()
                            logger.error(f"3D Secure FAILURE: Error Modal detected: {modal_text}")
                            self.take_screenshot("error_modal_detected")
                            
                            # Specific Check for Limit
                            if "limit" in modal_text.lower() and ("yetersiz" in modal_text.lower() or "yeterli değil" in modal_text.lower()):
                                if log_callback:
                                    log_callback("3DS_ERROR_LIMIT")
                                return False, "Yetersiz Bakiye/Limit Hatası"
                            
                            # General Error - Return the text found in modal
                             # General Error - Return the text found in modal
                            if log_callback:
                                log_callback(f"3DS_ERROR_MODAL: {modal_text[:50]}")
                            return False, f"İşlem Hatası: {modal_text}"

                    except Exception:
                        pass

                    # Check Main Page for "İşlem Başarısız" even if iframe is present
                    # (Sometimes the error is on the main page background or overlay)
                    try:
                        main_page_content = self.page.content()
                        if "İşlem Başarısız" in main_page_content or "Transaction Failed" in main_page_content:
                            logger.error("3D Secure FAILURE: 'İşlem Başarısız' text found on main page.")
                            if log_callback:
                                log_callback("3DS_ERROR_GENERIC") # Or specific if we can parse it
                            return False, "İşlem Başarısız (Main Page)"
                    except Exception:
                        pass
                    
                    time.sleep(3)
                
                # Final fallback after timeout
                self.take_screenshot("3d_secure_poll_timeout")
                
                # Last check: is iframe still there?
                if not self.page.query_selector(iframe_selector):
                    return True, "3D Secure completed (iframe gone after poll timeout)"
                
                return False, "Timeout: 3D Secure did not complete within poll window"
                # Removed defunct else block since Enter fallback handles missing buttons
            else:
                return False, "Input field for code not found"
        except Exception as e:
            logger.error(f"Error in _submit_sms_code: {e}")
            return False, str(e)

    def handle_3d_secure(self, log_callback=None) -> (bool, str):
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
                    self.take_screenshot("3d_secure_iframe_initial")
                    
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
                        force_submit_attempted = False
                        
                        while time.time() - sms_start_time < sms_wait_timeout:
                            try:
                                content = frame.content()
                                body_text = frame.inner_text('body').strip().replace('\n', ' ')
                                
                                # Check for Empty Iframe (typical 39-50 bytes for empty html/body)
                                if len(content) < 100 and not body_text:
                                    if int(time.time() - sms_start_time) > 15 and not force_submit_attempted:
                                        logger.warning("Iframe seems empty/stuck > 15s. Attempting to force submit the form...")
                                        try:
                                            # Find the form targeting this iframe (in the main page context)
                                            # We need to step out to main page to find the form
                                            # But 'self.page' is the main page.
                                            form_selector = '.Iframe_iframe-wrapper__form__dTpu6'
                                            form = self.page.query_selector(form_selector)
                                            if form:
                                                logger.info(f"Found form {form_selector}. Submitting via JS...")
                                                self.page.evaluate("document.querySelector('.Iframe_iframe-wrapper__form__dTpu6').submit()")
                                                force_submit_attempted = True
                                                time.sleep(5) # Wait for reload
                                                continue
                                            else:
                                                logger.error("Could not find the 3D Secure form to force submit.")
                                        except Exception as e:
                                            logger.error(f"Force submit failed: {e}")
                                            
                                # Debug: Periodic Dump
                                
                                # Debug: Periodic Dump
                                if int(time.time() - sms_start_time) % 10 == 0:
                                     logger.info(f"3DS Frame Text: {body_text[:100]}...")
                                     try:
                                         with open(f"debug_output/sms_frame_dump_{int(time.time())}.html", "w", encoding="utf-8") as f:
                                             f.write(content)
                                     except: pass

                                # Check for common keywords indicating code entry screen
                                # Use case-insensitive check
                                content_lower = content.lower()
                                keywords = ["sms", "şifre", "dogrulama", "doğrulama", "code", "password", "tek kullanımlık", "onay", "secure", "3d"]
                                
                                # Also check if any input field is visible
                                input_visible = False
                                try:
                                    # Quick check for common input types
                                    if frame.is_visible('input[type="password"]') or \
                                       frame.is_visible('input[name="otpCode"]') or \
                                       frame.is_visible('input[id="code"]') or \
                                       frame.is_visible('input[type="text"]'): # Broaden check
                                        input_visible = True
                                except:
                                    pass

                                if any(k in content_lower for k in keywords) or input_visible:
                                    # Take screenshot of the actual SMS entry screen
                                    # verify we haven't already done this repeatedly
                                    if int(time.time() - sms_start_time) % 10 == 0:
                                        self.take_screenshot("3d_secure_sms_screen_ready")
                                    
                                    if int(time.time() - sms_start_time) % 5 == 0:
                                        logger.info("Screen keywords matched or Input visible. Checking DB for SMS...")
                                        if log_callback:
                                            log_callback("3DS_WAITING_SMS")

                                    # Check Database for new SMS
                                    lookback_time = timezone.now() - timezone.timedelta(minutes=3)
                                    last_sms = SMSLog.objects.filter(received_at__gte=lookback_time).order_by('-received_at').first()
                                    
                                    if last_sms:
                                        logger.info(f"SMS found in DB (last 3 mins) from {last_sms.sender}: {last_sms.message_content}")
                                        if log_callback:
                                            log_callback(f"3DS_SMS_RECEIVED: {last_sms.message_content[:10]}...")
                                        
                                        # Extract Code
                                        match = re.search(r'\b\d{6}\b', last_sms.message_content)
                                        if match:
                                            code = match.group(0)
                                            logger.info(f"Extracted Code: {code}")
                                            self.take_screenshot("sms_code_found_entering")
                                            return self._submit_sms_code(iframe_selector, code, log_callback)
                                        else:
                                            logger.warning("SMS found but no 6-digit code extracted.")
                                    
                                    # Optional: Check for input field visibility just to log status
                                    if not code_entered:
                                         if frame.query_selector('input[type="password"]') or frame.query_selector('input[type="text"]'):
                                             pass
                                
                                if int(time.time() - sms_start_time) % 5 == 0:
                                    logger.info(f"Waiting for SMS... ({int(time.time() - sms_start_time)}s passed)")
                                    
                                time.sleep(2) 
                            
                            except Exception as e:
                                logger.warning(f"Error accessing frame content (Navigation?): {e}")
                                # If frame is detached/navigating, checking parent iframe again might be needed
                                # or simply continuing the loop until it stabilizes
                                time.sleep(1)
                        
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
