from django import forms
from .models import Order, CreditCard, Package, Operator

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['phone_number', 'operator', 'package', 'selected_card'] # Removed amount, package_id
        
    # Extra field for package selection, not directly in Order model but we use it to populate
    package = forms.ModelChoiceField(
        queryset=Package.objects.all(),
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'
        }),
        label="Paket Seçimi",
        empty_label="Paket Seçiniz"
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(OrderForm, self).__init__(*args, **kwargs)
        if user:
            self.fields['selected_card'].queryset = CreditCard.objects.filter(user=user)
        
        # Set default operator to Turkcell
        try:
            turkcell = Operator.objects.get(name__icontains='Turkcell')
            self.fields['operator'].initial = turkcell
            # Filter packages by Turkcell initially
            self.fields['package'].queryset = Package.objects.filter(operator=turkcell)
        except Operator.DoesNotExist:
            pass

        self.fields['operator'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'
        })
        self.fields['phone_number'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': '5XX XXX XX XX'
        })
        self.fields['selected_card'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'
        })

    def clean_selected_card(self):
        card = self.cleaned_data.get('selected_card')
        if card and not card.can_be_used:
            # Throw validation error on the form
            raise forms.ValidationError(f"Bu kartın 24 saatlik kullanım limiti ({card.usage_count_24h}/6) dolmuştur. Lütfen başka bir kart seçin.")
        return card

class CreditCardForm(forms.ModelForm):
    class Meta:
        model = CreditCard
        fields = ['alias', 'holder_name', 'card_number', 'exp_month', 'exp_year', 'cvv', 'balance']
        widgets = {
            'alias': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': 'Örn: Bonus Kartım'}),
            'holder_name': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'card_number': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'exp_month': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': 'AA', 'maxlength': '2'}),
            'exp_year': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': 'YYYY', 'maxlength': '4'}),
            'cvv': forms.TextInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'maxlength': '4'}),
            'balance': forms.NumberInput(attrs={'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': '0.00', 'step': '0.01'}),
        }

    def clean_exp_month(self):
        month = self.cleaned_data.get('exp_month')
        if month:
            # Ensure 2 digits
            return str(month).zfill(2)
        return month

    def clean_exp_year(self):
        year = self.cleaned_data.get('exp_year')
        if year:
            year_str = str(year)
            if len(year_str) == 2:
                return f"20{year_str}"
        return year

    def clean_card_number(self):
        number = self.cleaned_data.get('card_number')
        if number:
            # Remove spaces
            return number.replace(" ", "")
        return number
