from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from .models import Order, CreditCard, SMSLog, TestRun
from .forms import OrderForm, CreditCardForm

from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import re
import logging

@login_required
def dashboard(request):
    # Default: Last 24 hours
    now = timezone.now()
    default_start = now - timedelta(hours=24)
    query_params = {}
    
    # Check for filters
    # Check for filters
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    phone_search = request.GET.get('phone_search')
    
    orders_query = Order.objects.filter(user=request.user).exclude(package_id__regex=r'^\d+$')
    
    # Phone Search (Time Independent if no dates provided)
    if phone_search:
        orders_query = orders_query.filter(phone_number__icontains=phone_search)
        query_params['phone_search'] = phone_search

    if start_date_str and end_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # Filter by range (inclusive)
            orders_query = orders_query.filter(created_at__date__range=[start_date, end_date])
            
            query_params['start_date'] = start_date_str
            query_params['end_date'] = end_date_str
            is_filtered_by_24h = False
        except ValueError:
            # Fallback
            if not phone_search:
                orders_query = orders_query.filter(created_at__gte=default_start)
                is_filtered_by_24h = True
            else:
                is_filtered_by_24h = False
                
    elif start_date_str:
        # Only start date provided (act as single date filter)
        try:
             start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
             orders_query = orders_query.filter(created_at__date=start_date)
             query_params['start_date'] = start_date_str
             is_filtered_by_24h = False
        except ValueError:
             if not phone_search:
                 orders_query = orders_query.filter(created_at__gte=default_start)
                 is_filtered_by_24h = True
             else:
                 is_filtered_by_24h = False
    elif not phone_search:
        # Default view (Only if NO phone search)
        orders_query = orders_query.filter(created_at__gte=default_start)
        is_filtered_by_24h = True
    else:
        # Phone search is present but no dates -> Show all history for that phone
        is_filtered_by_24h = False

    # Order by newest first
    orders_query = orders_query.order_by('-created_at')

    # Pagination
    paginator = Paginator(orders_query, 10) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    if request.method == 'POST':
        form = OrderForm(request.POST, user=request.user) 
        if form.is_valid():
            order = form.save(commit=False)
            order.user = request.user
            
            # Handle Package selection
            selected_package = form.cleaned_data.get('package')
            if selected_package:
                order.package_id = selected_package.package_id
                order.amount = selected_package.price
            
            # Ensure operator matches package (optional safety check)
            if selected_package and order.operator != selected_package.operator:
                # If user changed operator but kept package, or logic mismatch. 
                # For now we trust the form or force operator from package
                order.operator = selected_package.operator
                
            order.save()
            return redirect('dashboard')
    else:
        form = OrderForm(user=request.user)

    cards = CreditCard.objects.filter(user=request.user)
    context = {
        'orders': page_obj, 
        'form': form,
        'cards': cards,
        'is_filtered_by_24h': is_filtered_by_24h,
        'start_date': query_params.get('start_date', ''),
        'end_date': query_params.get('end_date', ''),
        'query_params': query_params
    }
    return render(request, 'core/dashboard.html', context)

@login_required
def cards(request):
    user_cards = CreditCard.objects.filter(user=request.user)
    
    if request.method == 'POST':
        form = CreditCardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)
            card.user = request.user
            card.save()
            return redirect('cards')
    else:
        form = CreditCardForm()

    context = {
        'cards': user_cards,
        'form': form,
    }
    return render(request, 'core/cards.html', context)

from django.shortcuts import get_object_or_404

@login_required
def edit_card(request, pk):
    card = get_object_or_404(CreditCard, pk=pk, user=request.user)
    
    if request.method == 'POST':
        form = CreditCardForm(request.POST, instance=card)
        if form.is_valid():
            form.save()
            return redirect('cards')
        else:
            import sys
            print(f"DEBUG: Form Errors: {form.errors}", file=sys.stderr)
    else:
        form = CreditCardForm(instance=card)
    
    return render(request, 'core/card_edit.html', {'form': form, 'card': card})

@login_required
def delete_card(request, pk):
    card = get_object_or_404(CreditCard, pk=pk, user=request.user)
    if request.method == 'POST':
        card.delete()
        return redirect('cards')
    return render(request, 'core/card_confirm_delete.html', {'card': card})

@login_required
@require_POST
def top_up_card(request, pk):
    from decimal import Decimal
    card = get_object_or_404(CreditCard, pk=pk, user=request.user)
    amount_str = request.POST.get('amount', '0')
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            return redirect('cards')
        card.balance += amount
        card.save()
    except Exception:
        pass
    return redirect('cards')


from worker.tasks import run_test_flow

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def sms_webhook(request):
    """
    """
    try:
        logger.info(f"Raw Webhook Body: {request.body.decode('utf-8', errors='ignore')}")
        data = json.loads(request.body)
        sender = data.get('sender')
        body = data.get('body')

        if not sender or not body:
            return JsonResponse({'error': 'Missing fields'}, status=400)

        # Extract 6-digit code
        match = re.search(r'\b\d{6}\b', body)
        code = match.group(0) if match else None

        # Find the most recent PENDING or 3DS_WAITING order for this operator?
        # Ideally, the SMS body might contain order ID, but usually it doesn't.
        # We'll link it to the most recent '3DS_WAITING' order created in the last 5 minutes.
        # For simplicity in this demo, we just save the log. The Worker poll will find it.
        
        # Link logic updates: find latest order in 3DS_WAITING state
        # This is a heuristic.
        from django.utils import timezone
        from datetime import timedelta
        
        recent_order = Order.objects.filter(
            status='3DS_WAITING', 
            updated_at__gte=timezone.now() - timedelta(minutes=5)
        ).first()

        SMSLog.objects.create(
            sender=sender,
            message_content=body,
            related_order=recent_order 
        )
        
        logger.info(f"SMS received from {sender}: {code}")
        return JsonResponse({'status': 'success', 'code': code})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def test_runner(request):
    cards = CreditCard.objects.filter(user=request.user)
    return render(request, 'core/test_runner.html', {'cards': cards})

@login_required
@require_POST
def start_test(request):
    phone_number = request.POST.get('phone_number')
    package_id = request.POST.get('package_id')
    card_id = request.POST.get('card_id')
    
    test_run = TestRun.objects.create(operator_name="Turkcell")
    
    # Check card limit
    from core.models import CreditCard
    try:
        card = CreditCard.objects.get(id=card_id)
        if not card.can_be_used:
            return JsonResponse({'error': f'Bu kartın günlük kullanım limiti ({card.usage_count_24h}/6) dolmuştur. Lütfen başka bir kart seçin.'}, status=400)
    except CreditCard.DoesNotExist:
        return JsonResponse({'error': 'Kart bulunamadı'}, status=400)

    # Trigger Celery Task
    run_test_flow.delay(test_run.id, phone_number, package_id=package_id, card_id=card_id)
    
    return JsonResponse({'status': 'started', 'test_run_id': test_run.id})

@login_required
def tl_load(request):
    from .models import Package, Operator
    from django.core.paginator import Paginator
    from django.db.models import Q
    
    # 1. Base Filter: Only TL Transactions
    # We identify TL transactions by checking if the package_id corresponds to a 'TL Yükle' package
    # OR if the package_id is a digit (heuristic for TL amounts, e.g. "100", "200")
    
    tl_package_ids = list(Package.objects.filter(category='TL Yükle').values_list('package_id', flat=True))
    
    # Start with base query
    orders_query = Order.objects.filter(user=request.user)
    
    # Apply TL filter: ID in known TL list OR ID is purely numeric
    # This covers both synced packages and ad-hoc TL amounts
    if tl_package_ids:
        orders_query = orders_query.filter(Q(package_id__in=tl_package_ids) | Q(package_id__regex=r'^\d+$'))
    else:
        orders_query = orders_query.filter(package_id__regex=r'^\d+$')

    # 2. Apply Dashboard Filters (Date & Phone)
    now = timezone.now()
    default_start = now - timedelta(hours=24)
    query_params = {}
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    phone_search = request.GET.get('phone_search')
    is_filtered_by_24h = False # Default false for this view unless no filters? 
    # Actually user requested same logic as dashboard: default 24h if no other filter.
    
    if phone_search:
        orders_query = orders_query.filter(phone_number__icontains=phone_search)
        query_params['phone_search'] = phone_search

    if start_date_str and end_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            orders_query = orders_query.filter(created_at__date__range=[start_date, end_date])
            query_params['start_date'] = start_date_str
            query_params['end_date'] = end_date_str
        except ValueError:
            pass
    elif start_date_str:
        try:
             start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
             orders_query = orders_query.filter(created_at__date=start_date)
             query_params['start_date'] = start_date_str
        except ValueError:
             pass
    
    # Default 24h filter if no specific search/filter is applied
    if not phone_search and not start_date_str and not end_date_str:
         orders_query = orders_query.filter(created_at__gte=default_start)
         is_filtered_by_24h = True

    # Order by newest
    orders_query = orders_query.order_by('-created_at')

    # Pagination
    paginator = Paginator(orders_query, 10)
    page_number = request.GET.get('page')
    orders = paginator.get_page(page_number)

    cards = CreditCard.objects.filter(user=request.user)
    
    context = {
        'cards': cards, 
        'orders': orders,
        'query_params': query_params,
        'start_date': start_date_str or '',
        'end_date': end_date_str or '',
        'is_filtered_by_24h': is_filtered_by_24h
    }
    return render(request, 'core/tl_yukle.html', context)

@login_required
@require_POST
def start_tl_test(request):
    phone_number = request.POST.get('phone_number')
    amount = request.POST.get('amount')
    card_id = request.POST.get('card_id')
    
    test_run = TestRun.objects.create(operator_name="Turkcell TL")
    
    # Check card limit
    from core.models import CreditCard
    try:
        card = CreditCard.objects.get(id=card_id)
        if not card.can_be_used:
            return JsonResponse({'error': f'Bu kartın günlük kullanım limiti ({card.usage_count_24h}/6) dolmuştur. Lütfen başka bir kart seçin.'}, status=400)
    except CreditCard.DoesNotExist:
        return JsonResponse({'error': 'Kart bulunamadı'}, status=400)

    # Trigger Celery Task
    run_test_flow.delay(test_run.id, phone_number, amount=amount, card_id=card_id)
    
    return JsonResponse({'status': 'started', 'test_run_id': test_run.id})

@login_required
def get_test_status(request, test_run_id):
    try:
        test_run = TestRun.objects.get(id=test_run_id)
        return JsonResponse({
            'status': test_run.status,
            'logs': test_run.logs
        })
    except TestRun.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

@login_required
def sms_logs(request):
    logs = SMSLog.objects.all().order_by('-received_at')[:50] # Show last 50
    return render(request, 'core/sms_logs.html', {'logs': logs})

# Interactive Flow APIs
@login_required
@require_POST
def init_transaction(request):
    import redis
    phone_number = request.POST.get('phone_number')
    transaction_type = request.POST.get('transaction_type', 'Package')
    
    if not phone_number:
        return JsonResponse({'error': 'Phone number required'}, status=400)
        
    test_run = TestRun.objects.create(operator_name=f"Turkcell Interactive ({transaction_type})")
    
    # Trigger Task
    from worker.tasks import start_interactive_flow
    start_interactive_flow.delay(test_run.id, phone_number, transaction_type=transaction_type)
    
    return JsonResponse({'status': 'started', 'task_id': test_run.id})

@login_required
def check_transaction_status_api(request, task_id):
    import redis
    import os
    from core.models import Package, Operator, TestRun
    
    redis_host = os.getenv('REDIS_HOST', 'redis')
    print(f"DEBUG API: Connecting to Redis at {redis_host}")
    r = redis.Redis(host=redis_host, port=6379, db=0)
    
    # Check Redis status
    redis_key = f"transaction:{task_id}:status"
    status = r.get(redis_key)
    status = status.decode('utf-8') if status else "PENDING"
    
    print(f"DEBUG API: Checking key {redis_key} -> {status}") # DEBUG LOG
    
    # Get logs from DB to show progress
    try:
        test_run = TestRun.objects.get(id=task_id)
        logs = test_run.logs
    except TestRun.DoesNotExist:
        logs = ""
    
    response = {
        'status': status,
        'logs': logs
    }
    
    if status == "WAITING_SELECTION":
        # Fetch fresh packages
        try:
            turkcell = Operator.objects.get(name__icontains='Turkcell')
            packages = Package.objects.filter(operator=turkcell).values('id', 'name', 'price', 'category', 'package_id')
            pack_list = list(packages)
            print(f"DEBUG API: Found {len(pack_list)} packages for Turkcell") # DEBUG LOG
            response['packages'] = pack_list
        except Exception as e:
            logger.error(f"Error fetching packages: {e}")
            response['packages'] = []
            
    from django.core.serializers.json import DjangoJSONEncoder
    return JsonResponse(response, encoder=DjangoJSONEncoder)

@login_required
@require_POST
def complete_transaction(request):
    import redis
    import json
    import os
    from core.models import Order, CreditCard, Operator, Package, TestRun
    
    task_id = request.POST.get('task_id')
    package_id = request.POST.get('package_id') # automation ID / name
    card_id = request.POST.get('card_id')
    phone_number = request.POST.get('phone_number')

    if not all([task_id, package_id, card_id]):
         return JsonResponse({'error': 'Missing required fields (task_id, package_id, card_id)'}, status=400)

    # If phone_number is missing, try to fetch from TestRun logs or context if possible
    # For now, we will rely on frontend sending it.
    if not phone_number:
         return JsonResponse({'error': 'Phone number is required'}, status=400)
    
    redis_host = os.getenv('REDIS_HOST', 'redis')
    print(f"DEBUG API: Connecting to Redis at {redis_host}")
    r = redis.Redis(host=redis_host, port=6379, db=0)
    
    # Create Order
    try:
        # Resolve related objects
        turkcell = Operator.objects.get(name__icontains='Turkcell')
        card = CreditCard.objects.get(id=card_id)
        
        # Check card limit
        if not card.can_be_used:
            return JsonResponse({'error': f'Bu kartın günlük kullanım limiti ({card.usage_count_24h}/6) dolmuştur. Lütfen başka bir kart seçin.'}, status=400)

        # Get package details for price
        # package_id passed here is the 'package_id' field (string), NOT the DB ID
        pkg_obj = Package.objects.filter(package_id=package_id).first()
        price = pkg_obj.price if pkg_obj else 0
        package_name = pkg_obj.name if pkg_obj else package_id
        
        # Create Order Record
        order = Order.objects.create(
            user=request.user,
            operator=turkcell,
            package_id=package_id, # Storing the automation ID
            phone_number=phone_number,
            amount=price,
            status='PROCESSING'
        )
        
        # Prepare payload for Worker
        payload = json.dumps({
            'package_id': package_id,
            'card_id': card_id,
            'order_id': order.id
        })
        
        # Push to Redis
        r.set(f"transaction:{task_id}:selection", payload)
        
        return JsonResponse({'status': 'resumed', 'order_id': order.id})

    except Exception as e:
        logger.error(f"Failed to create order or resume transaction: {e}")
        return JsonResponse({'error': f'Transaction failed: {str(e)}'}, status=500)

@login_required
def bulk_orders(request):
    from core.models import Package, CreditCard, Operator
    
    # Fetch data for generic dropdowns (Global selection or Modal)
    try:
        turkcell = Operator.objects.get(name__icontains='Turkcell')
        packages = Package.objects.filter(operator=turkcell)
    except Exception:
        packages = []
        
    cards = CreditCard.objects.filter(user=request.user)
    
    context = {
        'packages': packages,
        'cards': cards,
    }
    return render(request, 'core/bulk_orders.html', context)

@login_required
def auto_orders(request):
    """View to list orders handled by the autonomous API integration."""
    from core.models import SystemSetting, CreditCard
    
    settings = SystemSetting.get_settings()
    cards = CreditCard.objects.filter(user=request.user)
    
    orders_query = Order.objects.filter(api_source='MATIK').order_by('-created_at')
    
    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter:
        orders_query = orders_query.filter(status=status_filter)
        
    paginator = Paginator(orders_query, 10)
    page_number = request.GET.get('page')
    orders = paginator.get_page(page_number)
    
    context = {
        'orders': orders,
        'status_filter': status_filter,
        'system_settings': settings,
        'cards': cards
    }
    return render(request, 'core/auto_orders.html', context)

@login_required
@require_POST
def update_system_settings(request):
    """AJAX endpoint to update global System settings."""
    from core.models import SystemSetting, CreditCard
    try:
        data = json.loads(request.body)
        is_active = data.get('is_autonomous_active')
        default_card_id = data.get('default_card_id')
        
        settings = SystemSetting.get_settings()
        
        if is_active is not None:
            settings.is_autonomous_active = bool(is_active)
            
        if default_card_id is not None:
            if default_card_id == '':
                settings.default_card = None
            else:
                card = CreditCard.objects.get(id=default_card_id, user=request.user)
                settings.default_card = card
                
        settings.save()
        return JsonResponse({'status': 'success', 'is_active': settings.is_autonomous_active, 'default_card_id': settings.default_card.id if settings.default_card else None})
    except Exception as e:
        logger.error(f"Error updating system settings: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
@require_POST
def define_package(request):
    """View to manually define an unknown package code and retry the order."""
    from core.models import Package, Operator
    import json
    
    order_id = request.POST.get('order_id')
    package_name = request.POST.get('package_name')
    
    if not order_id or not package_name:
        return JsonResponse({'status': 'error', 'message': 'Eksik bilgi'}, status=400)
        
    try:
        order = Order.objects.get(id=order_id)
        
        # Extract the code from raw_data
        raw_data = json.loads(order.raw_api_data)
        api_kontor = raw_data.get('api_kontor')
        
        if not api_kontor:
            return JsonResponse({'status': 'error', 'message': 'Küpür bulunamadı'}, status=400)
            
        turkcell = Operator.objects.first()
        
        # Update or Create the package definition
        Package.objects.update_or_create(
            operator=turkcell,
            code=api_kontor,
            defaults={
                'name': package_name,
                'package_id': 'UNDEFINED_WAITING_SYNC' # Will be filled when scraped or kept if just matching is needed
            }
        )
        
        # Resume the order processing
        order.status = Order.Status.PENDING
        order.log_message = "Küpür tanımlandı, yeniden deneniyor."
        order.save()
        
        from worker.tasks import process_autonomous_order
        process_autonomous_order.delay(order.id)
        
        return redirect('auto_orders')

    except Order.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Sipariş bulunamadı'}, status=404)
    except Exception as e:
        logger.error(f"Error defining package: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def cancel_order(request):
    """View to manually cancel an order."""
    order_id = request.POST.get('order_id')
    
    if not order_id:
        return JsonResponse({'status': 'error', 'message': 'Eksik bilgi'}, status=400)
        
    try:
        from core.models import Order
        order = Order.objects.get(id=order_id)
        
        if order.status in [Order.Status.COMPLETED, Order.Status.FAILED]:
            return JsonResponse({'status': 'error', 'message': 'Bu sipariş zaten sonlanmış.'}, status=400)
            
        order.status = Order.Status.FAILED
        order.log_message = "Kullanıcı tarafından iptal edildi."
        order.save()
        
        # Send callback to the API provider so they know it's cancelled
        from worker.services.matik_api import MatikAPIService
        MatikAPIService.send_callback(order.external_ref, 2)
        
        return redirect('auto_orders')

    except Order.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Sipariş bulunamadı'}, status=404)
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def packages(request):
    """View to list all packages and add new ones."""
    from core.models import Package, Operator
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add':
            operator_id = request.POST.get('operator_id')
            name = request.POST.get('name')
            code = request.POST.get('code')
            package_id = request.POST.get('package_id', '')
            price = request.POST.get('price')
            category = request.POST.get('category', 'General')
            
            try:
                operator = Operator.objects.get(id=operator_id)
                Package.objects.create(
                    operator=operator,
                    name=name,
                    code=code,
                    package_id=package_id or code,
                    price=price if price else None,
                    category=category
                )
            except Exception as e:
                logger.error(f"Error adding package: {e}")
        
        return redirect('packages')
    
    packages_list = Package.objects.select_related('operator').exclude(category='TL Yükle').order_by('operator__name', 'name')
    operators = Operator.objects.filter(is_active=True)
    
    context = {
        'packages': packages_list,
        'operators': operators,
    }
    return render(request, 'core/packages.html', context)


@login_required
@require_POST
def edit_package(request, pk):
    """Edit an existing package."""
    from core.models import Package, Operator
    
    try:
        package = Package.objects.get(id=pk)
        package.name = request.POST.get('name', package.name)
        package.code = request.POST.get('code', package.code)
        package.package_id = request.POST.get('package_id', package.package_id)
        price = request.POST.get('price')
        package.price = price if price else None
        package.category = request.POST.get('category', package.category)
        
        operator_id = request.POST.get('operator_id')
        if operator_id:
            package.operator = Operator.objects.get(id=operator_id)
        
        package.save()
    except Exception as e:
        logger.error(f"Error editing package: {e}")
    
    return redirect('packages')


@login_required
@require_POST
def delete_package(request, pk):
    """Delete a package."""
    from core.models import Package
    
    try:
        Package.objects.get(id=pk).delete()
    except Exception as e:
        logger.error(f"Error deleting package: {e}")
    
    return redirect('packages')
