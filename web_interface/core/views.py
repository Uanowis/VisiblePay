from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from .models import Order, CreditCard
from .forms import OrderForm, CreditCardForm

@login_required
def dashboard(request):
    orders = Order.objects.filter(user=request.user)[:10]  # Filter by user
    
    if request.method == 'POST':
        form = OrderForm(request.POST, user=request.user) 
        if form.is_valid():
            order = form.save(commit=False)
            order.user = request.user
            order.save()
            return redirect('dashboard')
    else:
        form = OrderForm(user=request.user)

    context = {
        'orders': orders,
        'form': form,
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

