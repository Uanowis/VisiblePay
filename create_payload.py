import google.generativeai as genai
from PIL import Image
import os
import io

# Setup
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not set in environment.")
    exit(1)

genai.configure(api_key=api_key)

# Use the model user requested, or fallback if needed.
# Since we want to test "Nano Banana", we try that first.
model_name = 'models/nano-banana-pro-preview' 
# Valid fallback: 'models/gemini-2.0-flash'

print(f"Using model: {model_name}")
model = genai.GenerativeModel(model_name)

image_path = "capche.jpeg"
try:
    with Image.open(image_path) as img:
        print(f"Original size: {img.size}")
        
        # Resize if too big (width > 512) to save tokens
        if img.width > 512:
            ratio = 512 / img.width
            new_height = int(img.height * ratio)
            img = img.resize((512, new_height), Image.Resampling.LANCZOS)
            print(f"Resized to: {img.size}")
        
        # Prompt
        prompt = "Analyze this image and extract the text. Return ONLY the alphanumeric characters (letters and numbers) visible in the captcha. Do not include spaces or any other text."
        
        # Generate
        response = model.generate_content([prompt, img])
        print("-" * 20)
        print("RESULT:")
        print(response.text.strip())
        print("-" * 20)

except Exception as e:
    print(f"Error: {e}")
