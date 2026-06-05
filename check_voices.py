from dotenv import load_dotenv
import os, requests

load_dotenv()
key = os.getenv("ELEVENLABS_API_KEY", "")
r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})

if r.ok:
    voices = r.json().get("voices", [])
    print(f"Total voices: {len(voices)}\n")
    for v in voices:
        cat = v.get("category", "")
        name = v["name"]
        vid = v["voice_id"]
        print(f"  [{cat}] {name} | {vid}")
else:
    print(f"Error {r.status_code}: {r.text[:300]}")
