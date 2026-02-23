
import time
import logging

logger = logging.getLogger(__name__)

class PaymentMixin:
    """Mixin for payment form filling logic."""

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
            
            # Screenshot: Card details filled
            self.take_screenshot("card_details_filled")
            
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

            # Screenshot: After agreement checkbox
            self.take_screenshot("agreement_checkbox_done")

            # Submit
            # Wait for button to be enabled (it might be disabled until checkbox is checked)
            self.page.wait_for_selector(self.Maps["submit_payment"], state="visible")
            # Smart wait for button to become enabled
            try:
                self.page.wait_for_function(f"document.querySelector('{self.Maps['submit_payment']}').disabled == false", timeout=2000)
            except:
                self.page.wait_for_timeout(1000) # Fallback
            
            submit_btn = self.page.locator(self.Maps["submit_payment"])
            if submit_btn.is_disabled():
                 logger.warning("Submit button is disabled! Checkbox might not be checked.")
                 # Try forcing checkbox again
                 self.page.click('.ant-checkbox-wrapper') 
                 self.page.wait_for_timeout(500)
            
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
            self.page.wait_for_timeout(2000)
            
            # Screenshot: After submit clicked, before 3D secure
            self.take_screenshot("after_payment_submit")
            
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
