# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

import sys
import asyncio
import logging
from .vars import Var
from aiohttp import web
from pyrogram import idle
from WebStreamer import utils
from WebStreamer import StreamBot
from WebStreamer.server import web_server
from WebStreamer.bot.clients import initialize_clients


logging.basicConfig(
    level=logging.DEBUG if Var.DEBUG else logging.INFO,
    datefmt="%d/%m/%Y %H:%M:%S",
    format="[%(asctime)s][%(name)s][%(levelname)s] ==> %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],)

logging.getLogger("aiohttp").setLevel(logging.DEBUG)
logging.getLogger("pyrogram").setLevel(logging.DEBUG)
logging.getLogger("aiohttp.web").setLevel(logging.DEBUG)

server = web.AppRunner(web_server())

# if sys.version_info[1] > 9:
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
# else:
loop = asyncio.get_event_loop()



import socket

def check_connection():
    print("--- DIAGNOSING NETWORK ---", flush=True)
    targets = [
        ("149.154.167.50", 443), # DC2 (HTTPS)
        ("149.154.167.50", 80),  # DC2 (HTTP)
        ("149.154.167.50", 5222),# DC2 (Generic TCP)
    ]
    for host, port in targets:
        try:
            print(f"Testing {host}:{port}...", flush=True)
            s = socket.create_connection((host, port), timeout=5)
            # Try to send one byte to see if it hangs (Firewall check)
            s.send(b"\x00") 
            s.close()
            print(f"✅ Success: Connected & Sent to {host}:{port}", flush=True)
        except Exception as e:
            print(f"❌ Failed: {host}:{port} - {e}", flush=True)
    print("--- DIAGNOSIS COMPLETE ---", flush=True)

async def start_services():
    check_connection()
    print("------------------ STARTING SERVICES ------------------", flush=True)
    
    # 1. Start Web Server FIRST to bind port 7860 (Satisfy HF Health Check)
    print("Starting Web Server...", flush=True)
    await server.setup()
    await web.TCPSite(server, Var.BIND_ADDRESS, Var.PORT).start()
    print("Web Server Started!", flush=True)

    # 2. Start Telegram Bot (can take time)
    logging.info("Initializing Telegram Bot")
    try:
        print("Attempting to start StreamBot...", flush=True)
        await StreamBot.start()
        print("StreamBot started!", flush=True)
    except Exception as e:
        print(f"FAILED to start StreamBot: {repr(e)}", flush=True)
        logging.error(f"Failed to start StreamBot: {repr(e)}")
        # If bot fails, we should probably exit to restart, OR keep server running to show error page?
        # For now, let's keep running so we can see logs
        # return 

    bot_info = await StreamBot.get_me()
    logging.debug(bot_info)
    StreamBot.username = bot_info.username
    logging.info("Initialized Telegram Bot")
    
    print("Initializing additional clients...", flush=True)
    await initialize_clients()
    print("Additional clients initialized.", flush=True)
    
    if Var.KEEP_ALIVE:
        asyncio.create_task(utils.ping_server())
        
    logging.info("Service Started")
    if bot_info and bot_info.first_name:
        logging.info("bot =>> {}".format(bot_info.first_name))
    if bot_info and bot_info.dc_id:
        logging.info("DC ID =>> {}".format(str(bot_info.dc_id)))
    await idle()

    # Fallback if idle() exits early (common in some envs)
    while True:
        await asyncio.sleep(3600)

async def cleanup():
    try:
        if server:
            await server.cleanup()
        if StreamBot:
            await StreamBot.stop()
    except Exception as e:
        logging.warning(f"Error during cleanup: {e}")

if __name__ == "__main__":
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        pass
    except Exception as err:
        logging.error(str(err))
    finally:
        # Prevent crash if loop is already closed or client already stopped
        try:
            loop.run_until_complete(cleanup())
        except Exception:
            pass
        # loop.stop() # Automatically handled by run_until_complete usually
        logging.info("Stopped Services")