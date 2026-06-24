# ocr.py - API Cloud OCR 
"""Extract number plate text using Plate Recognizer API (Zero Local RAM)."""

import logging
import requests
from typing import Optional
from config import PLATE_REC_TOKEN

logger = logging.getLogger(__name__)

def extract_number_plate(image_bytes: bytes) -> Optional[str]:
    """
    Sends image bytes to Plate Recognizer API.
    Consumes 0MB of local processing RAM.
    """
    if not PLATE_REC_TOKEN or PLATE_REC_TOKEN == "your_actual_api_token_here":
        logger.warning("Plate Recognizer API Token not configured. Skipping OCR.")
        return None

    try:
        # Post the raw image bytes directly to the cloud API
        response = requests.post(
            'https://api.platerecognizer.com/v1/plate-reader/',
            data={'regions': 'in'},  # Optimize explicitly for Indian number plate formatting
            files={'upload': ('image.jpg', image_bytes)},
            headers={'Authorization': f'Token {PLATE_REC_TOKEN}'},
            timeout=10               # Safeguard to prevent your bot from hanging if the network lags
        )
        
        if response.status_code in (200, 201):
            data = response.json()
            results = data.get('results', [])
            
            if results:
                # Select the prediction with the highest structural confidence score
                plate = results[0].get('plate', '').upper()
                logger.info(f"Cloud API successfully detected plate: {plate}")
                return plate
                
            logger.info("Cloud API processed image successfully but found no vehicle plate.")
            return None
            
        logger.error(f"API Error: Status {response.status_code} - {response.text}")
        return None

    except Exception as e:
        logger.error(f"Cloud OCR Request failed: {e}")
        return None
