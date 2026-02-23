import os
import sys
from twocaptcha import TwoCaptcha

class CaptchaSolver:
    def __init__(self):
        self.api_key = os.getenv("CAPTCH_API_KEY")
        if not self.api_key:
            print("WARNING: CAPTCH_API_KEY is not set.")
            self.solver = None
        else:
            self.solver = TwoCaptcha(self.api_key)

    def solve_base64(self, base64_str: str) -> str:
        """
        Solves base64 encoded captcha image using 2Captcha.
        """
        if not self.solver:
             print("Cannot solve: Solver not initialized (Missing API Key).")
             return ""

        # Remove header if present
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        try:
            # 2Captcha accepts base64 strings directly
            # method='base64' is handled by the library if we pass the string correctly or save to file
            # The library typically prefers file path, but supports base64 too.
            # Ideally we save temp file to be safe and robust.
            
            import tempfile
            import base64
            
            # Save base64 to temp file
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                temp_file.write(base64.b64decode(base64_str))
                temp_file_path = temp_file.name

            try:
                print(f"Sending captcha to 2Captcha... (File: {temp_file_path})")
                result = self.solver.normal(temp_file_path)
                print(f"2Captcha Result: {result}")
                return result['code'].upper()
            finally:
                # Cleanup
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            
        except Exception as e:
            print(f"2Captcha Failed: {e}")
            return ""

    def solve(self, image_data: bytes) -> str:
        """
        Wrapper for raw bytes input.
        """
        import base64
        base64_str = base64.b64encode(image_data).decode('utf-8')
        return self.solve_base64(base64_str)
