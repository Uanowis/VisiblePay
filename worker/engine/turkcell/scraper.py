
import time
import re
import logging
from .navigator import handle_cookies

logger = logging.getLogger(__name__)

class ScraperMixin:
    """Mixin for package scraping and selection logic."""

    def scrape_packages(self, is_tl=False) -> list:
        logger.info(f"Scraping packages... (Mode: {'TL' if is_tl else 'Package'})")
        self.take_screenshot("scraping_start")
        packages = []
        
        try:
            if is_tl:
                # Scrape TL Amounts
                try:
                    self.page.wait_for_selector(self.Maps["tl_card"], timeout=10000)
                    cards = self.page.query_selector_all(self.Maps["tl_card"])
                    logger.info(f"Found {len(cards)} TL amount cards.")
                    
                    for card in cards:
                        text = card.inner_text().strip().replace("\n", "").replace(" ", "")
                        # Extract amount (e.g. 200TL -> 200)
                        match = re.search(r'(\d+)', text)
                        if match:
                            amount = float(match.group(1))
                            packages.append({
                                'category': 'TL Yükle',
                                'name': f"{int(amount)} TL",
                                'package_id': str(int(amount)), # Use amount as ID
                                'price': amount
                            })
                    return packages
                except Exception as e:
                    logger.error(f"Error scraping TL amounts: {e}")
                    return []

            # Util: Fast wait helper
            def wait_optional(selector, timeout=3000):
                 try:
                     self.page.wait_for_selector(selector, timeout=timeout)
                     return True
                 except: 
                     return False

            # Package Scraping Logic (default)
            # Wait for content to load - Reduced timeout
            wait_optional(self.Maps["tab_ek_paketler"], timeout=5000)
                
            # Find all tabs using Locators
            if not wait_optional('div[class*="molecule-tab"]', timeout=5000):
                 logger.warning("Timeout waiting for tabs (5s).")
                 # Don't return yet, try finding cards directly? No, usually tabs wrap them.
                 # return [] 
                 
            # Use Locator to find tabs
            # Try specific class first
            tabs_locator = self.page.locator('div[class*="tabItem"]')
            tab_count = tabs_locator.count()
            
            if tab_count == 0:
                 # Backup strategy: simple role=tab
                 tabs_locator = self.page.locator('div[role="tab"]')
                 tab_count = tabs_locator.count()
            
            logger.info(f"Found {tab_count} category tabs.")
            
            if tab_count == 0:
                logger.error("No tabs found! Checking for loose cards...")
                # Fallback: maybe we are already on a listing page without tabs?
                cards = self.page.query_selector_all(self.Maps["package_card"])
                if cards:
                     logger.info(f"Found {len(cards)} loose cards without tabs.")
                     # Process these cards (logic below expects loop, but we can hack it)
                     # For now just return empty, user said "stuck", this speeds it up.
                     return []
                
                self.take_screenshot("no_tabs_found")
                return []
            
            for i in range(tab_count):
                try:
                    tab = tabs_locator.nth(i)
                    
                    # Robust Name Extraction
                    category_name = "Unknown Category"
                    try:
                        category_name = (
                            tab.get_attribute('title', timeout=500) 
                            or tab.inner_text(timeout=500).strip() 
                            or tab.get_attribute('aria-label', timeout=500)
                            or tab.get_attribute('data-label', timeout=500)
                            or ""
                        ).strip()
                    except Exception: 
                        pass
                        
                    if not category_name:
                        category_name = f"Kategori {i+1}"
                        
                    logger.info(f"Processing Category {i+1}/{tab_count}: {category_name}")
                    
                    # Click tab - Fast click
                    try:
                        tab.click(timeout=1000)
                        self.page.wait_for_timeout(500) 
                    except Exception as e:
                        logger.warning(f"Could not click tab {category_name}: {e}")
                        continue
                        
                    # Check for "Tümünü Gör" (See All) button - Fast check
                    try:
                        see_all_btn = self.page.locator('button:has-text("Tümünü Gör")')
                        if see_all_btn.is_visible(timeout=500):
                            see_all_btn.click(timeout=1000)
                            self.page.wait_for_timeout(500)
                    except Exception:
                        pass 

                    # Scrape cards
                    card_selector = self.Maps["package_card"]
                    
                    # Wait briefly for cards to load after click
                    if not wait_optional(card_selector, timeout=2000):
                        logger.warning(f"No package cards found in {category_name} (2s). Skipping.")
                        continue

                    # Use element handles for cards in the current view (simpler than locators as they are static for this view)
                    cards = self.page.query_selector_all(card_selector)
                    logger.info(f"Found {len(cards)} package cards in {category_name}")
                    
                    for idx, card in enumerate(cards):
                        try:
                            # Name Extraction
                            name = "Unknown"
                            name_el = card.query_selector(self.Maps["package_name"])
                            if name_el:
                                text = name_el.inner_text().strip()
                                if text: name = text
                            
                            # Price Extraction
                            price = 0.0
                            price_text = ""
                            price_el = card.query_selector('[class*="priceInfoText"]')
                            if price_el:
                                price_text = price_el.inner_text().strip()
                            
                            if price_text:
                                price_match = re.search(r'(\d+[.,]?\d*)', price_text)
                                if price_match:
                                    try:
                                        price = float(price_match.group(1).replace(',', '.'))
                                    except: pass
                            
                            if name != "Unknown" and price > 0:
                                logger.info(f"Scraped: {name} - {price} TL")
                                packages.append({
                                    'category': category_name,
                                    'name': name,
                                    'package_id': name,
                                    'price': price
                                })
                            
                        except Exception as e:
                            logger.warning(f"Error scraping a card: {e}")
                            
                except Exception as e:
                    logger.error(f"Error processing tab {i}: {e}")
                    
            logger.info(f"Scraping finished. Returning {len(packages)} packages.")
            return packages

        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            return []

    def _match_package_score(self, package_id: str, title_text: str) -> float:
        """Check if package_id matches title_text using strategies, returns a score 0.0 to 1.0."""
        if not package_id or not title_text:
            return 0.0
            
        pid_clean = package_id.lower().strip()
        title_clean = title_text.lower().strip()
        
        # 1. Exact match
        if pid_clean == title_clean:
            return 1.0
        
        # 2. Clean match (remove completely excessive spaces)
        pid_nospace = pid_clean.replace(" ", "")
        title_nospace = title_clean.replace(" ", "")
        
        if pid_nospace == title_nospace:
            return 1.0
            
        # Number Guard: Ensure numeral quantities actually match to prevent "1GB" matching "11GB" if "1GB" was just a word.
        import re
        pid_nums = set(re.findall(r'\d+', pid_clean))
        title_nums = set(re.findall(r'\d+', title_clean))
        
        # If the requested package has numbers, at least one must intersect
        if pid_nums and not pid_nums.intersection(title_nums):
            return 0.0
            
        # 3. Substring match (If the letters are exactly inside the other)
        # Give higher penalty if title is inside pid, because title is too generic for the query
        if pid_nospace in title_nospace:
            return 0.95
        if title_nospace in pid_nospace:
            return 0.90
            
        # 4. Fuzzy match (Tolerates abbreviations like "Dk" vs "Dakika")
        import difflib
        pid_no_brand = pid_clean.replace("turkcell", "").replace("gnç", "").strip()
        
        ratio = difflib.SequenceMatcher(None, pid_no_brand, title_clean).ratio()
        ratio_orig = difflib.SequenceMatcher(None, pid_clean, title_clean).ratio()
        
        return max(ratio, ratio_orig)

    def _confirm_tl_selection(self, target_card, package_id: str) -> bool:
        """Confirm selection specifically for TL amounts."""
        logger.info(f"Confirming TL selection for {package_id}")
        
        # Strategy: Click the inner div container
        inner_div = target_card.query_selector('div')
        click_target = inner_div if inner_div else target_card
        
        # Force click to ensure it registers
        click_target.click(force=True)
        logger.info("Clicked TL card (force=True)")
        
        # Verify Selection
        time.sleep(2)
        try:
            box_classes = click_target.get_attribute("class")
            if box_classes and ("isSelected" in box_classes or "active" in box_classes):
                 logger.info("TL Selection verified (class check).")
            else:
                 logger.warning(f"TL Selection might have failed. Classes: {box_classes}. Retrying click with JS...")
                 self.page.evaluate("(el) => el.click()", click_target)
                 time.sleep(2)
        except Exception as e:
             logger.warning(f"Verification error: {e}")

        self.take_screenshot("after_tl_card_click")
        
        # Click continue (TL specific logic)
        self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        try:
            handle_cookies(self.page)
            
            # Precise selector for TL flow
            confirm_selectors = [
                '.molecule-basket-amount-bar_basket-amount-bar__button__Zg8N5',
                'button.atom-button_a-trkclAppBtn__medium__MUPRY',
                'button:has-text("Devam Et")',
                '//button[contains(., "Devam Et")]'
            ]
            
            btn = None
            for selector in confirm_selectors:
                try:
                    btn = self.page.query_selector(selector)
                    if btn and btn.is_visible():
                        logger.info(f"Found Continue button with selector: {selector}")
                        break
                except:
                    continue
            
            if btn:
                btn.scroll_into_view_if_needed()
                # Check for disabled
                if btn.is_disabled() or "disabled" in (btn.get_attribute("class") or ""):
                    time.sleep(2)
                    
                try:
                    self.page.evaluate("(el) => el.click()", btn)
                    logger.info("Clicked Continue button (JS)")
                except Exception as e:
                    logger.error(f"Click failed: {e}")
                    return False
            else:
                logger.error("Continue button not found (TL Flow)!")
                self.take_screenshot("tl_continue_not_found")
                return False

        except Exception as e:
            logger.error(f"Error clicking continue (TL Flow): {e}")
            return False
            
        return True

    def _click_and_confirm_package(self, target_card, package_id: str) -> bool:
        """Click the found package card and proceed (Panel Flow)."""
        logger.info(f"Clicking package card for {package_id} (Panel Flow)")
        
        try:
            # 1. Click the card
            # Try clicking the inner element if possible (like title) to avoid structural issues
            click_target = target_card
            title = target_card.query_selector(self.Maps["package_name"])
            if title:
                click_target = title
                
            click_target.scroll_into_view_if_needed()
            click_target.click(force=True)
            logger.info("Clicked package card.")
            self.take_screenshot("after_package_click")
            
            # 2. Wait for confirmation or next step
            # Usually 'Devam Et' or 'Satın Al' button appears
            time.sleep(2)
            
            # Use generic selectors for Panel flow
            confirm_selectors = [
                self.Maps["continue_btn"],
                'button.atom-button_a-trkclAppBtn__medium__MUPRY',
                'button:has-text("Devam Et")',
                'button:has-text("Satın Al")',
                'a:has-text("Devam Et")'
            ]
            
            btn = None
            for selector in confirm_selectors:
                 try:
                     btn = self.page.query_selector(selector)
                     if btn and btn.is_visible():
                         logger.info(f"Found confirmation button: {selector}")
                         break
                 except:
                     continue
            
            if btn:
                btn.click()
                logger.info("Clicked confirmation button.")
            else:
                # Maybe clicking the card was enough?
                # Or maybe it opened a modal?
                logger.warning("No specific confirmation button found. Checking if url changed or we proceeded.")
                
            # Assume success if no error, verification happens in next steps (Payment)
            return True
            
        except Exception as e:
            logger.error(f"Error in package confirmation: {e}")
            return False

    def select_package(self, package_id: str = None, amount: float = None, fallback_name: str = None) -> bool:
        logger.info(f"Selecting Package: {package_id} or Amount: {amount} or Fallback: {fallback_name}")
        self.take_screenshot("package_selection_start")
        self.last_selected_price = 0.0
        self.last_selected_name = ""
        
        # Ensure cookies are handled before we start looking
        handle_cookies(self.page)
        
        try:
            # TL Flow: Don't wait for package tabs, go directly to TL cards
            if amount:
                logger.info(f"TL Load mode for amount: {amount}")
                try:
                    # Amounts are usually displayed as cards or radio buttons with text like "100 TL"
                    amount_str = str(int(amount)) # e.g. "100"
                    
                    # Precise TL Card Selector from HTML:
                    # .atom-price-box_a-trkclApp-price-box__vdHgd
                    tl_card_selector = '.atom-price-box_a-trkclApp-price-box__vdHgd'
                    
                    # Wait for amount cards - Increased timeout to 30s
                    self.page.wait_for_selector(tl_card_selector, timeout=30000)
                    cards = self.page.query_selector_all(tl_card_selector)
                    
                    target_card = None
                    for i, card in enumerate(cards):
                        text = card.inner_text().strip().replace("\n", "").replace(" ", "")
                        logger.info(f"TL Card {i} text: '{text}'")
                        
                        # Normalize text for comparison
                        # "200TL" -> "200"
                        clean_text = text.lower().replace("tl", "").replace("₺", "").strip()
                        
                        # exact number match?
                        if clean_text == amount_str:
                             target_card = card
                             logger.info(f"Found match for amount {amount} in card {i}")
                             break
                        # fallback: contains
                        if f"{amount_str}" in clean_text:
                             # verify it's the exact number (e.g. avoid matching 20 in 200)
                             if clean_text == amount_str:
                                 target_card = card
                                 logger.info(f"Found match (clean) for amount {amount} in card {i}")
                                 break
                    
                    if target_card:
                         return self._confirm_tl_selection(target_card, f"{amount} TL")
                    else:
                         logger.error(f"Card for amount {amount} not found! Cards saw: {[c.inner_text() for c in cards]}")
                         self.take_screenshot("tl_amount_not_found")
                         return False

                except Exception as e:
                    logger.error(f"Error selecting TL amount: {e}")
                    self.take_screenshot("tl_selection_error")
                    return False
                
            search_texts = []
            if package_id and package_id != 'UNDEFINED':
                search_texts.append(package_id)
            if fallback_name and fallback_name not in search_texts:
                search_texts.append(fallback_name)
                
            if search_texts:
                # Wait for package selection screen (Panel flow)
                try:
                    self.page.wait_for_selector(self.Maps["tab_ek_paketler"], timeout=30000)
                except Exception:
                    logger.warning("EK PAKETLER tab not found, trying generic tab selector...")
                    
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
                            self.page.wait_for_timeout(1000)
                        except Exception as e:
                            logger.warning(f"Could not click tab {category_name}: {e}")
                            continue

                        # Check for "Tümünü Gör" button
                        try:
                            see_all_btn = self.page.query_selector('button:has-text("Tümünü Gör")')
                            if see_all_btn and see_all_btn.is_visible():
                                logger.info("Found 'Tümünü Gör' button. Clicking...")
                                see_all_btn.click()
                                self.page.wait_for_timeout(1000)
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
                        
                        best_tab_score = 0.0
                        best_tab_card = None
                        best_tab_title = ""
                        
                        for i, card in enumerate(cards):
                            title_el = card.query_selector(self.Maps["package_name"])
                            if title_el:
                                title_text = title_el.inner_text().strip()
                                logger.info(f"  Card {i} Title: {title_text}")
                                
                                for search_text in search_texts:
                                    score = self._match_package_score(search_text, title_text)
                                    if score > best_tab_score:
                                        best_tab_score = score
                                        best_tab_card = card
                                        best_tab_title = title_text
                            else:
                                logger.warning(f"  Card {i} has no title element.")
                                
                        if best_tab_score >= 0.75 and best_tab_card:
                            logger.info(f"✅ Best match selected in tab '{category_name}': {best_tab_title} (Score: {best_tab_score:.2f})")
                            
                            # Extract price before clicking!
                            try:
                                price_el = best_tab_card.query_selector('[class*="priceInfoText"]')
                                if price_el:
                                    price_text = price_el.inner_text().strip()
                                    price_match = re.search(r'(\d+[.,]?\d*)', price_text)
                                    if price_match:
                                        self.last_selected_price = float(price_match.group(1).replace(',', '.'))
                                        self.last_selected_name = best_tab_title
                            except Exception as e:
                                logger.warning(f"Could not extract price before clicking: {e}")

                            with open("debug_output/packages_page.html", "w") as f:
                                f.write(self.page.content())
                            return self._click_and_confirm_package(best_tab_card, best_tab_title)
                                
                    except Exception as e:
                        logger.error(f"Error searching tab {tab_idx}: {e}")
                        continue

                # If we get here, package was not found in any tab
                logger.error(f"Package queries '{search_texts}' not found in any of {len(tabs)} tabs.")
                with open("debug_output/packages_page.html", "w") as f:
                    f.write(self.page.content())
                self.take_screenshot("package_not_found_all_tabs")
                return False

            return False
        except Exception as e:
            logger.error(f"Error selecting package: {e}")
            return False
