from celery import shared_task
from playwright.sync_api import sync_playwright
import logging
import traceback
from django.utils import timezone
from core.models import TestRun, CreditCard, Order, Operator
from .engine.factory import OperatorFactory
# Import the concrete implementation to ensure registration (if not auto-discovered)
from .engine.turkcell import TurkcellOperator
from .services.matik_api import MatikAPIService
import difflib

# Register manually for now since we don't have auto-discovery logic yet
OperatorFactory.register('turkcell', TurkcellOperator)

import os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

logger = logging.getLogger(__name__)

@shared_task
def poll_matik_api():
    """
    Periodically checks the Matik API for new orders.
    Creates Order objects and triggers processing.
    """
    from core.models import SystemSetting
    settings = SystemSetting.get_settings()
    if not settings.is_autonomous_active:
        logger.info("Autonomous system is currently DISABLED. Skipping system polling.")
        return
        
    orders = MatikAPIService.fetch_pending_orders()
    logger.info(f"Polled Matik API: Found {len(orders)} orders.")
    
    for order_data in orders:
        ref = order_data.get('ref')
        phone = order_data.get('phone')
        operator_tag = order_data.get('operator')
        kontor = order_data.get('kontor')
        
        if not ref or not phone or not operator_tag or not kontor:
            logger.warning(f"Incomplete order data from API: {order_data}")
            continue
            
        # Check if already exists
        existing_order = Order.objects.filter(external_ref=ref).first()
        if existing_order:
            if existing_order.status == Order.Status.FAILED:
                logger.info(f"Retrying previously FAILED order from API: Ref {ref}")
                
                # Reconstruct what the API sent us in case they fixed a typo
                import json
                raw_data = {
                    'original_xml': order_data.get('raw', ''),
                    'api_operator': operator_tag,
                    'api_kontor': kontor,
                    'api_paketadi': order_data.get('paketadi', '')
                }
                
                # Reset the status for a clean run and update details
                existing_order.status = Order.Status.PENDING
                existing_order.log_message = "Yeniden deneme (API üzerinden tekrar gönderildi)"
                existing_order.raw_api_data = json.dumps(raw_data)
                existing_order.phone_number = phone
                existing_order.save()
                
                # Trigger processing again
                process_autonomous_order.delay(existing_order.id)
            
            # Skip creating a new one whether it was FAILED (we just updated it) or it's currently processing/success
            continue
            
        logger.info(f"Creating new order from API: Ref {ref}, Phone {phone}, Op {operator_tag}, Kontor {kontor}")
        
        # Create Order
        turkcell = Operator.objects.first() # Default to first/Turkcell for now
        
        # Save kontor to raw_api_data or similar to pass it without modifying model heavily
        import json
        raw_data = {
            'original_xml': order_data.get('raw', ''),
            'api_operator': operator_tag,
            'api_kontor': kontor,
            'api_paketadi': order_data.get('paketadi', '')
        }
        
        new_order = Order.objects.create(
            phone_number=phone,
            operator=turkcell,
            external_ref=ref,
            api_source='MATIK',
            raw_api_data=json.dumps(raw_data),
            status=Order.Status.PENDING
        )
        
        # Trigger processing
        process_autonomous_order.delay(new_order.id)

@shared_task
def process_autonomous_order(order_id):
    """
    Autonomous flow for processing an API order.
    """
    try:
        order = Order.objects.get(id=order_id)
        order.status = Order.Status.PROCESSING
        order.save()
        
        # Pull the globally selected default card
        from core.models import SystemSetting
        settings = SystemSetting.get_settings()
        card = settings.default_card

        if not card:
            logger.error(f"No credit card available for order {order_id}")
            order.status = Order.Status.FAILED
            order.log_message = "No credit card available."
            order.save()
            MatikAPIService.send_callback(order.external_ref, 2)
            return
            
        # Bind card to order for usage statistics ("Günlük Kullanım")
        order.selected_card = card
        order.save()

        # Check limit
        if not card.can_be_used:
            logger.error(f"Default credit card {card.id} limit reached for order {order_id}")
            order.status = Order.Status.FAILED
            order.log_message = f"Varsayılan kartın günlük limiti ({card.usage_count_24h}/6) dolmuştur."
            order.save()
            MatikAPIService.send_callback(order.external_ref, 2)
            return

        import json
        try:
            raw_data = json.loads(order.raw_api_data)
            api_operator = raw_data.get('api_operator', '')
            api_kontor = raw_data.get('api_kontor', '')
            api_paketadi = raw_data.get('api_paketadi', api_kontor) # Fallback to kontor if paketadi empty
        except:
            api_operator = ''
            api_kontor = ''
            api_paketadi = ''
            
        # Determine Transaction Type
        current_transaction_type = "Package"
        is_tl_load = False
        if api_operator.lower() == 'turkcelltam':
            current_transaction_type = "TL"
            is_tl_load = True

        # Matching Logic Before Browser Launch to save time and handle wait
        matched_package_id = None
        matched_amount = None
        fallback_name = None
        
        if is_tl_load:
            try:
                matched_amount = float(api_kontor)
            except ValueError:
                logger.error(f"Invalid TL amount from API: {api_kontor}")
                order.status = Order.Status.FAILED
                order.log_message = f"Invalid TL amount: {api_kontor}"
                order.save()
                MatikAPIService.send_callback(order.external_ref, 2)
                return
        else:
            # Package Loading - Check if code exists
            from core.models import Package
            turkcell = Operator.objects.first()
            package_obj = Package.objects.filter(operator=turkcell, code=api_kontor).first()
            
            if package_obj:
                if package_obj.package_id != 'UNDEFINED':
                    # Exact ID match available
                    matched_package_id = package_obj.package_id
                    order.amount = package_obj.price
                    # User might have populated package_id with the API kontor code incorrectly.
                    # Send the readable name as fallback_name just in case!
                    fallback_name = package_obj.name
                else:
                    # User manually defined it in the panel but didn't know the exact internal website ID. 
                    # Use their defined "name" (e.g. "Fırsat 1GB") as the fuzzy match fallback!
                    logger.info(f"Package {api_kontor} has no internal package_id, but user defined name '{package_obj.name}'. Using it for fuzzy match.")
                    fallback_name = package_obj.name
                    order.amount = package_obj.price
            else:
                logger.warning(f"Unknown or undefined package code: {api_kontor}. Will attempt fuzzy match in browser using: {api_paketadi}")
                fallback_name = api_paketadi
                # Do NOT return, we will proceed to launch the browser to find and fuzzy match the package

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context()
            page = context.new_page()
            
            operator = OperatorFactory.get_operator('turkcell', page, card)
            
            # Step 1: Navigate
            operator.navigate_to_base_url()
            
            # Step 2: Select Type & Phone
            operator.select_upload_type(current_transaction_type)
            operator.fill_phone(order.phone_number)
            
            # Step 3: Captcha
            def captcha_callback(msg):
                if msg == "CAPTCHA_PHASE_2":
                    logger.info(f"Order {order_id}: Moving to Captcha Phase 2 (2. defa deneniyor)")
                    order.log_message = "2. defa captcha deneniyor"
                    order.save()
                    
            if not operator.solve_captcha(log_callback=captcha_callback):
                logger.error(f"Captcha failed for order {order_id}")
                order.status = Order.Status.FAILED
                order.log_message = "Captcha Failed"
                order.save()
                MatikAPIService.send_callback(order.external_ref, 2) 
                return

            # Step 4: Scrape
            scraped_data = operator.scrape_packages(is_tl=is_tl_load)
            
            # If we had a package ID, we don't need to match string anymore, we know it from db
            # But let's verify if the scraped data has our matched_package_id
            # This is optional, but good for sanity
                  
            # Step 5: Select Package
            selection_success = False
            if current_transaction_type == "TL" and matched_amount:
                if operator.select_package(amount=matched_amount):
                    selection_success = True
                    order.amount = matched_amount
                    order.resolved_package_name = getattr(operator, 'last_selected_name', f"{matched_amount} TL")
                    order.save()
            elif matched_package_id or fallback_name:
                if operator.select_package(package_id=matched_package_id, fallback_name=fallback_name):
                    selection_success = True
                    order.resolved_package_name = getattr(operator, 'last_selected_name', fallback_name or matched_package_id)
                    order.save()
            
            if not selection_success:
                logger.error(f"Package selection failed for code {api_kontor}")
                
                if fallback_name and not matched_package_id:
                    # It was an unknown package and we couldn't even fuzzy match it
                    order.status = Order.Status.WAITING_MANUAL_ACTION
                    order.log_message = f"Küpür bulunamadı veya eşleşmedi: {api_kontor}"
                    order.save()
                    
                    from core.models import Package
                    turkcell = Operator.objects.first()
                    Package.objects.get_or_create(
                        operator=turkcell,
                        code=api_kontor,
                        defaults={'name': f'Bilinmeyen Paket ({api_kontor})', 'package_id': 'UNDEFINED'}
                    )
                else:
                    # It was a known package but we couldn't find it on the page
                    order.status = Order.Status.FAILED
                    order.log_message = f"Could not match/select package with code: {api_kontor}"
                    order.save()
                    MatikAPIService.send_callback(order.external_ref, 2) 
                    
                return
                
            elif fallback_name and not matched_package_id:
                # We successfully fuzzy matched an unknown package! Auto-map it.
                from core.models import Package
                turkcell = Operator.objects.first()
                matched_id = getattr(operator, 'last_selected_name', fallback_name)
                scraped_price = getattr(operator, 'last_selected_price', 0.0)
                
                logger.info(f"Auto-mapping API code '{api_kontor}' to package '{matched_id}' with price {scraped_price}")
                Package.objects.update_or_create(
                    operator=turkcell,
                    code=api_kontor,
                    defaults={'name': matched_id, 'package_id': matched_id, 'price': scraped_price}
                )
                order.amount = scraped_price

            # Step 6: Payment
            if not operator.process_payment():
                 logger.error("Payment processing failed")
                 order.status = Order.Status.FAILED
                 order.save()
                 MatikAPIService.send_callback(order.external_ref, 2)
                 return
                 
            order.status = Order.Status.WAITING_3DS
            order.save()
            
            # Step 7: 3D Secure
            success, message = operator.handle_3d_secure(log_callback=lambda msg: logger.info(f"Order {order_id}: {msg}"))
            
            if success:
                order.status = Order.Status.COMPLETED
                order.save()
                MatikAPIService.send_callback(order.external_ref, 1)

                # Deduct balance from card
                try:
                    if card and order.amount:
                        card.balance -= order.amount
                        card.save()
                        logger.info(f"Deducted {order.amount} from card {card.alias} for autonomous order {order.id}. New balance: {card.balance}")
                        if card.balance < 0:
                            order.balance_went_negative = True
                            order.save()
                            logger.warning(f"Card {card.alias} balance went negative: {card.balance}")
                except Exception as balance_err:
                    logger.error(f"Balance deduction error in autonomous order: {balance_err}")
            else:
                order.status = Order.Status.FAILED
                order.log_message = f"3DS Failed: {message}"
                order.save()
                MatikAPIService.send_callback(order.external_ref, 2)
                
            # Capture final screenshot before closing
            import os
            try:
                final_screenshot_name = f"order_{order.id}_final"
                operator.take_screenshot(final_screenshot_name)
                final_screenshot_path = f"debug_output/{final_screenshot_name}.png"
                
                if os.path.exists(final_screenshot_path):
                    from django.core.files import File
                    with open(final_screenshot_path, "rb") as f:
                        order.final_screenshot.save(f"{order.id}_final.png", File(f), save=True)
                    # Clean up the local file after saving to Django's media storage
                    os.remove(final_screenshot_path)
            except Exception as ss_err:
                logger.error(f"Failed to capture final screenshot: {ss_err}")
                
            browser.close()

    except Exception as e:
        logger.error(f"Autonomous Processing Error: {e}\n{traceback.format_exc()}")
        try:
            order = Order.objects.get(id=order_id)
            order.status = Order.Status.FAILED
            order.log_message = str(e)
            order.save()
            MatikAPIService.send_callback(order.external_ref, 2)
        except:
            pass

@shared_task
def start_interactive_flow(test_run_id, phone_number, transaction_type="Package"):
    """
    Starts the interactive flow:
    1. Launches browser
    2. Enters Phone & Solves Captcha
    3. Scrapes Packages & Updates DB
    4. Waits for user selection via Redis
    5. Completes Payment
    """
    import redis
    import json
    import time
    from core.models import Package, Operator
    
    # Redis connection
    r = redis.Redis(host='redis', port=6379, db=0)
    
    try:
        test_run = TestRun.objects.get(id=test_run_id)
        test_run.append_log(f"Starting Interactive Flow ({transaction_type})...")
        test_run.status = 'RUNNING'
        test_run.save()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context()
            page = context.new_page()
            
            # Initialize with dummy card, will update later
            operator = OperatorFactory.get_operator('turkcell', page, None)
            
            # Step 1: Entry
            test_run.append_log("Navigating and identifying...")
            operator.navigate_to_base_url()
            
            # Select Type (Package or TL)
            operator.select_upload_type(transaction_type)
            
            operator.fill_phone(phone_number)
            
            if not operator.solve_captcha():
                test_run.append_log("Captcha Failed.")
                test_run.status = 'FAILED'
                test_run.save()
                r.set(f"transaction:{test_run_id}:status", "FAILED")
                return "Captcha Failed"
                
            test_run.append_log("Captcha Solved. Scraping packages...")
            
            # Clear old packages for this operator to ensure fresh data
            # Ideally we might want to flag them as inactive instead, but for now delete 
            # to avoid mixing old/test data with live data.
            try:
                turkcell = Operator.objects.get(name__icontains='Turkcell')
                Package.objects.filter(operator=turkcell).delete()
                test_run.append_log("Cleared old cached packages.")
            except Exception as e:
                logger.warning(f"Could not clear packages: {e}")
            
            # Step 2: Scrape
            # Pass is_tl=True if transaction_type is TL
            scraped_data = operator.scrape_packages(is_tl=(transaction_type == "TL"))
            test_run.append_log(f"Scraped {len(scraped_data)} options.")
            
            # Update DB
            turkcell = Operator.objects.get(name__icontains='Turkcell')
            for pkg in scraped_data:
                try:
                    # Truncate to avoid DataError (max_length=100)
                    safe_name = pkg['name'][:99]
                    safe_category = pkg['category'][:99]
                    safe_id = pkg['package_id'][:99]
                    
                    Package.objects.update_or_create(
                        operator=turkcell,
                        name=safe_name,
                        defaults={
                            'price': pkg['price'],
                            'category': safe_category,
                            'package_id': safe_id
                        }
                    )
                except Exception as db_err:
                    logger.warning(f"Failed to save package {pkg.get('name', 'Unknown')}: {db_err}")
                    # Continue to next package instead of crashing
                    continue
            
            # Notify Frontend via Redis
            # Set status to WAITING_SELECTION
            r.set(f"transaction:{test_run_id}:status", "WAITING_SELECTION")
            test_run.append_log("Waiting for user selection...")
            test_run.save()
            
            # Step 3: Wait for Selection
            # Wait up to 3 minutes
            selection_data = None
            for _ in range(90): # 90 * 2s = 180s
                raw_selection = r.get(f"transaction:{test_run_id}:selection")
                if raw_selection:
                    selection_data = json.loads(raw_selection)
                    break
                time.sleep(2)
                
            if not selection_data:
                test_run.append_log("Timeout waiting for user selection.")
                test_run.status = 'FAILED'
                test_run.save()
                operator.take_screenshot("interactive_timeout")
                r.set(f"transaction:{test_run_id}:status", "FAILED")
                return "Timeout"
                
            # Resume Flow
            test_run.append_log(f"Resuming with package: {selection_data['package_id']}")
            r.set(f"transaction:{test_run_id}:status", "PROCESSING")
            
            # Load Card
            card_id = selection_data['card_id']
            card = CreditCard.objects.get(id=card_id)
            operator.card = card # Update operator card
            
            order_id = selection_data.get('order_id')
            from core.models import Order
            
            # Step 4: Select Package
            selection_result = False
            if transaction_type == "TL":
                # For TL, the package_id in selection_data is actually the amount string
                amount_val = float(selection_data['package_id'])
                if operator.select_package(amount=amount_val):
                    selection_result = True
            else:
                if operator.select_package(package_id=selection_data['package_id']):
                    selection_result = True

            if selection_result:
                test_run.append_log("Package Selected.")
            else:
                test_run.append_log("Package Selection Failed.")
                test_run.status = 'FAILED'
                test_run.save()
                if order_id:
                     Order.objects.filter(id=order_id).update(status='FAILED')
                r.set(f"transaction:{test_run_id}:status", "FAILED")
                return "Package Selection Failed"
                
            # Step 5: Payment
            if operator.process_payment():
                test_run.append_log("Payment Submitted.")
                # Update Order to 3DS_WAITING if successful so far
                if order_id:
                     Order.objects.filter(id=order_id).update(status='3DS_WAITING')
            else:
                test_run.append_log("Payment Logic Failed.")
                test_run.status = 'FAILED'
                test_run.save()
                if order_id:
                     Order.objects.filter(id=order_id).update(status='FAILED')
                r.set(f"transaction:{test_run_id}:status", "FAILED")
                return "Payment Failed"
                
            # Step 6: 3D Secure
            test_run.append_log("Waiting for 3D Secure...")
            success, message = operator.handle_3d_secure(log_callback=test_run.append_log)
            
            if success:
                 test_run.append_log("3D Secure Completed.")
                 test_run.append_log(f"Result: {message}")
                 test_run.status = 'SUCCESS'
                 if order_id:
                     Order.objects.filter(id=order_id).update(status='COMPLETED')
                     # Deduct balance from card
                     try:
                         order_obj = Order.objects.get(id=order_id)
                         if order_obj.selected_card and order_obj.amount:
                             c = order_obj.selected_card
                             c.balance -= order_obj.amount
                             c.save()
                             logger.info(f"Deducted {order_obj.amount} from card {c.alias}. New balance: {c.balance}")
                             if c.balance < 0:
                                 order_obj.balance_went_negative = True
                                 order_obj.save()
                                 logger.warning(f"Card {c.alias} balance went negative: {c.balance}")
                     except Exception as balance_err:
                         logger.error(f"Balance deduction error: {balance_err}")
            else:
                 test_run.append_log(f"3D Secure Failed: {message}")
                 test_run.status = 'FAILED'
                 if order_id:
                     Order.objects.filter(id=order_id).update(status='FAILED')
                 
            test_run.save()
            r.set(f"transaction:{test_run_id}:status", test_run.status)
            
            operator.take_screenshot(f"final_{test_run_id}")
            browser.close()

    except Exception as e:
        error_msg = f"Interactive Flow Failed: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        if 'test_run' in locals():
            test_run.append_log(error_msg)
            test_run.status = 'FAILED'
            test_run.save()
            r.set(f"transaction:{test_run_id}:status", "FAILED")

@shared_task
def run_test_flow(test_run_id, phone_number, package_id=None, card_id=None, amount=None):
    """
    Executes a test flow for the given parameters (Package or Amount) and updates the TestRun model.
    """
    try:
        test_run = TestRun.objects.get(id=test_run_id)
        test_run.append_log("Starting Test Flow...")
        
        card = CreditCard.objects.get(id=card_id)
        test_run.append_log(f"Using Card: {card.alias}")

        with sync_playwright() as p:
            # Must be True for Docker unless Xvfb is set up
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage']) 
            # Note: On a server without display, use headless=True or xvfb
            
            context = browser.new_context()
            page = context.new_page()
            
            operator = OperatorFactory.get_operator('turkcell', page, card)
            test_run.append_log("Operator Initialized.")

            # Step 1: Navigate
            test_run.append_log("Navigating to Base URL...")
            operator.navigate_to_base_url()
            operator.take_screenshot(f"step1_{test_run_id}")
            test_run.append_log("Navigation Complete.")

            # Step 1.5: Select Type
            if amount:
                 test_run.append_log("Selecting Upload Type: TL")
                 operator.select_upload_type("TL")
            else:
                 test_run.append_log("Selecting Upload Type: Package")
                 operator.select_upload_type("Package")

            # Step 2: Fill Phone
            test_run.append_log(f"Filling Phone: {phone_number}...")
            operator.fill_phone(phone_number)
            test_run.append_log("Phone Filled.")

            # Step 3: Solve Captcha
            test_run.append_log("Solving Captcha...")
            if operator.solve_captcha():
                 test_run.append_log("Captcha Solved.")
            else:
                 test_run.append_log("Captcha Failed.")
                 test_run.status = 'FAILED'
                 test_run.save()
                 return "Captcha Failed"

            # Step 4: Select Package or Amount
            if package_id:
                test_run.append_log(f"Selecting Package: {package_id}...")
            elif amount:
                test_run.append_log(f"Selecting TL Amount: {amount}...")
            
            if operator.select_package(package_id=package_id, amount=amount):
                test_run.append_log("Selection Successful.")
            else:
                test_run.append_log("Selection Failed.")
                # We might continue to show payment page if manual intervention happened? 
                # For test, we fail.
                test_run.status = 'FAILED'
                test_run.save()
                return "Selection Failed"

            # Step 5: Payment
            test_run.append_log("Filling Payment Details...")
            if operator.process_payment():
                test_run.append_log("Payment Details Filled & Submitted.")
            else:
                test_run.append_log("Payment Logic Failed.")
                test_run.status = 'FAILED'
                test_run.save()
                return "Payment Failed"

            # Step 6: 3D Secure Verification
            test_run.append_log("Waiting for 3D Secure...")
            success, message = operator.handle_3d_secure(log_callback=test_run.append_log)
            
            if success:
                 test_run.append_log("3D Secure Iframe detected & Code Submitted.")
                 test_run.append_log(f"3D Secure Result Snippet: {message}")
                 test_run.status = 'SUCCESS'
            else:
                 test_run.append_log(f"3D Secure handling failed: {message}")
                 test_run.status = 'FAILED'

            test_run.save()
            operator.take_screenshot(f"final_{test_run_id}")
            browser.close()

    except Exception as e:
        error_msg = f"Test Failed with Error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        if 'test_run' in locals():
            test_run.append_log(error_msg)
            test_run.status = 'FAILED'
            test_run.save()
