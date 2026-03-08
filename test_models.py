import os
from google import genai
from dotenv import load_dotenv
load_dotenv()

client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
for m in client.models.list():
    if 'embed' in m.name.lower():
        print(m.name)
