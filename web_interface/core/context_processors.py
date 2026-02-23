import os
from django.core.cache import cache
from worker.utils.captcha_solver import CaptchaSolver
import logging

logger = logging.getLogger(__name__)

def captcha_balance(request):
    """
    Context processor to inject 2Captcha balance into all templates.
    Caches the result for 30 minutes to save API requests.
    """
    # Only calculate if the user is authenticated 
    if not request.user.is_authenticated:
        return {}

    balance = cache.get('captcha_balance')
    
    if balance is None:
        try:
            api_key = os.getenv("CAPTCH_API_KEY")
            if api_key:
                solver_instance = CaptchaSolver()
                # Assuming CaptchaSolver initialized successfully
                if solver_instance.solver:
                    balance = solver_instance.solver.balance()
                    # Cache for 30 minutes (1800 seconds)
                    cache.set('captcha_balance', balance, 1800)
                else:
                    balance = 'API Key Hatası'
            else:
                balance = 'Eksik Key'
        except Exception as e:
            logger.error(f"Error fetching 2Captcha balance: {e}")
            balance = 'Hata'
            cache.set('captcha_balance', balance, 300) # Cache error very briefly (5 min)

    return {'captcha_balance': balance}
