from dotenv import load_dotenv
import os
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

load_dotenv()
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

result = client.text_to_speech.convert_with_timestamps(
    voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
    text="Hello world.",
    model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
    voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
)

print("Type:", type(result))
print("Attrs:", [a for a in dir(result) if not a.startswith("_")])
if hasattr(result, "alignment"):
    a = result.alignment
    print("Alignment type:", type(a))
    print("Alignment attrs:", [x for x in dir(a) if not x.startswith("_")])
