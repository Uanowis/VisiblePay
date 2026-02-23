import requests
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)

class MatikAPIService:
    BASE_URL_TALEP = "http://bayi.matiksistem.com/servis/turkcell_talep.php"
    BASE_URL_SONUC = "http://bayi.matiksistem.com/servis/turkcell_sonuc.php"
    
    # Credentials (should be in env vars ideally)
    KOD = "matik"
    SIFRE = "sistem"

    @classmethod
    def fetch_pending_orders(cls):
        """
        Fetches pending orders from the API.
        Returns a list of dictionaries: [{'phone': '...', 'ref': '...', 'package': '...'}]
        """
        params = {
            'kod': cls.KOD,
            'sifre': cls.SIFRE
        }
        
        try:
            response = requests.get(cls.BASE_URL_TALEP, params=params, timeout=10)
            response.raise_for_status()
            
            content_str = response.content.decode('iso-8859-9', errors='ignore').strip()
            
            if not content_str:
                print("Empty response from API")
                return []
                
            # Safely wrap the content in a dummy root tag in case API returns multiple <talep> elements without a root
            import re
            content_str = re.sub(r'<\?xml.*?\?>', '', content_str).strip()
            xml_string = f"<dummy_root>{content_str}</dummy_root>"
            
            root = ET.fromstring(xml_string)
            
            orders = []
                
            # Loop through ALL elements deeply in case they are nested or sibling root nodes
            for child in root.iter():
                if child.tag in ['talep', 'islem']:
                    data = {}
                    for item in child:
                        data[item.tag] = item.text
                    
                    if 'id' in data and 'numara' in data:
                        # Extract basic fields
                        ref = data.get('id')
                        phone = data.get('numara')
                        operator_tag = data.get('operator')
                        kontor = data.get('kontor')
                        
                        # Pack them into the expected dictionary format for the task
                        orders.append({
                            'ref': ref,
                            'phone': phone,
                            'operator': operator_tag,
                            'kontor': kontor,
                            'raw': ET.tostring(child, encoding='unicode')
                        })
            
            return orders
            
        except ET.ParseError as e:
            logger.error(f"XML Parse Error: {e}. Content: {response.text[:100]}...")
            return []
        except requests.RequestException as e:
            logger.error(f"API Request Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected Error in fetch_pending_orders: {e}")
            return []

    @classmethod
    def send_callback(cls, ref, status):
        """
        Sends result callback to the API.
        status: 1 (Success), 2 (Fail)
        """
        params = {
            'kod': cls.KOD,
            'sifre': cls.SIFRE,
            'ref': ref,
            'durum': status
        }
        
        try:
            response = requests.get(cls.BASE_URL_SONUC, params=params, timeout=10)
            response.raise_for_status()
            logger.info(f"Callback sent for ref {ref} with status {status}. Response: {response.text}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send callback for ref {ref}: {e}")
            return False
