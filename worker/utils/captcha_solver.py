import ddddocr
import base64

class CaptchaSolver:
    def __init__(self):
        self.ocr = ddddocr.DdddOcr()

    def solve(self, image_data: bytes) -> str:
        """
        Solves the captcha using ddddocr.
        :param image_data: Bytes of the captcha image.
        :return: Solved text.
        """
        res = self.ocr.classification(image_data)
        return res

    def solve_base64(self, base64_str: str) -> str:
        """
        Solves base64 encoded captcha image.
        """
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        
        image_bytes = base64.b64decode(base64_str)
        return self.solve(image_bytes)
