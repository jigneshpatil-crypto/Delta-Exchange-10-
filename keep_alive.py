import os
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("KeepAlive")

def ping_server():
    """Pings the Render app URL to prevent it from spinning down."""
    url = os.getenv("RENDER_APP_URL")
    if not url:
        logger.warning("RENDER_APP_URL not set in environment. Keep-alive disabled.")
        return

    # Ensure URL has /health endpoint
    if not url.endswith("/health"):
        url = url.rstrip("/") + "/health"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logger.info(f"Keep-alive ping successful: {url}")
        else:
            logger.warning(f"Keep-alive ping failed with status {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Keep-alive ping error: {e}")

if __name__ == "__main__":
    interval = int(os.getenv("KEEP_ALIVE_INTERVAL", 300))
    logger.info(f"Starting keep-alive service. Pinging every {interval} seconds.")
    
    # Wait a bit for the main server to start before pinging
    time.sleep(30)
    
    while True:
        ping_server()
        time.sleep(interval)
