# Taken from megadlbot_oss <https://github.com/eyaadh/megadlbot_oss/blob/master/mega/webserver/routes.py>
# Thanks to Eyaadh <https://github.com/eyaadh>

import re
import time
import math
import logging
import secrets
import mimetypes
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from WebStreamer.bot import multi_clients, work_loads
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from WebStreamer import Var, utils, StartTime, __version__, StreamBot

logger = logging.getLogger("routes")


routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + getattr(StreamBot, "username", "Starting..."),
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": __version__,
        }
    )


@routes.get(r"/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([0-9a-f]{%s})(\d+)$" % (Var.HASH_LENGTH), path)
        if match:
            secure_hash = match.group(1)
            message_id = int(match.group(2))
        else:
            message_id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return await media_streamer(request, message_id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logger.critical(str(e), exc_info=True)
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

async def media_streamer(request: web.Request, message_id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if Var.MULTI_CLIENT:
        logger.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logger.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logger.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logger.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(message_id)
    logger.debug("after calling get_file_properties")
    
    
    if utils.get_hash(file_id.unique_id, Var.HASH_LENGTH) != secure_hash:
        logger.debug(f"Invalid hash for message with ID {message_id}")
        raise InvalidHash
    
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )
    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "attachment"

    if mime_type:
        if not file_name:
            try:
                file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"
            except (IndexError, AttributeError):
                file_name = f"{secrets.token_hex(2)}.unknown"
    else:
        if file_name:
            mime_type = mimetypes.guess_type(file_id.file_name)
        else:
            mime_type = "application/octet-stream"
            file_name = f"{secrets.token_hex(2)}.unknown"

    if "video/" in mime_type or "audio/" in mime_type or "/html" in mime_type:
        disposition = "inline"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )
@routes.get("/api/list")
async def list_files_handler(request):
    try:
        # Get query parameters
        channel_id_str = request.query.get("channel", str(Var.BIN_CHANNEL))
        limit = int(request.query.get("limit", 50))
        offset_id = int(request.query.get("offset_id", 0))

        # Validate channel ID
        try:
            channel_id = int(channel_id_str)
        except ValueError:
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        files = []
        
        # Determine offset for pagination
        # Pyrogram's get_chat_history uses offset_id (message_id) to start fetching OLDER messages.
        # If offset_id is 0, it fetches the newest messages.
        
        async for message in StreamBot.get_chat_history(chat_id=channel_id, limit=limit, offset_id=offset_id):
            if message.document or message.video or message.audio or message.photo:
                # determine media type and properties
                file_name = "Unknown"
                file_size = 0
                mime_type = "application/octet-stream"
                unique_id = ""
                
                media = None
                type_str = "unknown"
                width = 0
                height = 0
                duration = 0
                
                if message.document:
                    media = message.document
                    type_str = "document"
                elif message.video:
                    media = message.video
                    type_str = "video"
                    width = media.width
                    height = media.height
                    duration = media.duration
                elif message.audio:
                    media = message.audio
                    type_str = "audio"
                    duration = media.duration
                elif message.photo:
                    media = message.photo
                    type_str = "photo"
                    # Photo doesn't have file_name usually
                    file_name = f"photo_{message.date}.jpg"
                    width = media.width
                    height = media.height
                
                if media:
                    if hasattr(media, "file_name") and media.file_name:
                        file_name = media.file_name
                    if hasattr(media, "file_size"):
                        file_size = media.file_size
                    if hasattr(media, "mime_type") and media.mime_type:
                        mime_type = media.mime_type
                    if hasattr(media, "file_unique_id"):
                        unique_id = media.file_unique_id

                # Generate Stream Link
                # Using the existing logic for calculating hash if needed, or simple ID based if the bot supports it.
                # The existing stream_handler uses message_id and hash.
                
                # We need to construct the URL that points to THIS server's stream handler.
                # stream_handler pattern: /{path} -> checks hash and message_id
                
                # Generate Hash
                from WebStreamer import utils 
                # Assuming utils.get_hash exists as per line 85 of original file
                # But we need the file_id object to get unique_id? No, we have unique_id from message.
                
                # Check how stream_url is generated in bot/plugins/stream.py usually
                # But here we will just manually construct it using the same logic as stream_handler expects.
                
                # stream_handler expects: /hash:message_id or /message_id?hash=...
                # Let's use the cleaner /message_id?hash=... format if possible, or /<hash><message_id>
                
                # Original code regex for path: r"^([0-9a-f]{%s})(\d+)$"
                # So it expects hash + message_id concatenated.
                
                log_msg = await StreamBot.get_messages(channel_id, message.id)
                # We need the unique_id from the log channel message to generate the hash IF the bot 
                # verifies hashes against the log channel. 
                # However, for simplicity in this "Gallery" mode, we might just assume 
                # the user has access if they know the link. 
                
                # Wait, the bot verifies hash: 
                # if utils.get_hash(file_id.unique_id, Var.HASH_LENGTH) != secure_hash: raise InvalidHash
                # So we MUST generate the correct hash based on the media's unique_id.
                
                secure_hash = utils.get_hash(unique_id, Var.HASH_LENGTH)
                
                stream_url = f"{Var.URL}{secure_hash}{message.id}"
                
                files.append({
                    "id": message.id,
                    "name": file_name,
                    "size": file_size,
                    "type": type_str,
                    "mime_type": mime_type,
                    "stream_url": stream_url,
                    "caption": message.caption or "",
                    "date": int(message.date.timestamp()),
                    "width": width,
                    "height": height, 
                    "duration": duration,
                    "views": message.views or 0
                })

        return web.json_response({"files": files})

    except Exception as e:
        logger.error(str(e), exc_info=True)
        return web.json_response({"error": str(e)}, status=500)
