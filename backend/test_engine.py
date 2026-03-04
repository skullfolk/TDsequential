import requests
import json
import traceback
import sys

# Import run_pipeline directly to test it in the same environment
from app.services.scheduler import run_pipeline

try:
    print("Running pipeline synchronously for GC=F...")
    result = run_pipeline("GC=F", "XAUUSD")
    if result:
        print("✅ Pipeline succeeded!")
        print(f"Total Score: {result.get('confluence', {}).get('total_score')}")
    else:
        print("❌ Pipeline returned None")
except Exception as e:
    print("❌ Exception caught:")
    traceback.print_exc()
