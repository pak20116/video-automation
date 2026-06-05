from dotenv import load_dotenv
import os
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Image-capable models:")
for m in client.models.list():
    name = m.name
    if any(kw in name.lower() for kw in ["image", "imagen", "flash", "vision"]):
        actions = getattr(m, "supported_actions", []) or []
        print(f"  {name}  |  actions: {actions}")
