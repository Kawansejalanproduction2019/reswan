import discord
import json

def build_v2_card(title: str = None, description: str = None, fields: list = None, color: int = None, buttons: list = None, footer: str = None, media_url: str = None, attachment_filename: str = None):
    """
    Membangun struktur JSON untuk Discord Component Type 17 (Layout V2).
    """
    card_components = []
    
    content_text = ""
    if title:
        content_text += f"# {title}\n"
    if description:
        content_text += f"{description}\n\n"
        
    if fields:
        for field in fields:
            name = field.get("name", "")
            value = field.get("value", "")
            content_text += f"**{name}**\n{value}\n\n"
            
    if footer:
        content_text += f"*{footer}*"
        
    if content_text.strip():
        card_components.append({
            "type": 10,
            "id": 100,
            "content": content_text.strip()
        })
    
    # Add media if provided
    if media_url or attachment_filename is not None:
        media_obj = {}
        if attachment_filename is not None:
            media_obj["url"] = f"attachment://{attachment_filename}"
        elif media_url:
            media_obj["url"] = media_url
            
        card_components.append({
            "type": 12,
            "id": 150,
            "items": [{
                "media": media_obj,
                "description": None,
                "spoiler": False
            }]
        })
    
    # Add buttons
    if buttons:
        card_components.append({
            "type": 14,
            "id": 101,
            "spacing": 1,
            "divider": True
        })
        
        # Chunk buttons into groups of 5
        for row_idx in range(0, len(buttons), 5):
            button_chunk = buttons[row_idx:row_idx+5]
            button_components = []
            for i, btn in enumerate(button_chunk):
                b = {
                    "type": 2,
                    "id": 200 + row_idx + i,
                    "style": btn.get("style", 1),
                    "label": btn.get("label", "Button")
                }
                if "custom_id" in btn:
                    b["custom_id"] = btn["custom_id"]
                if "url" in btn:
                    b["url"] = btn["url"]
                if "emoji" in btn:
                    b["emoji"] = {"name": btn["emoji"]} if isinstance(btn["emoji"], str) else btn["emoji"]
                button_components.append(b)
                
            card_components.append({
                "type": 1,
                "id": 102 + (row_idx // 5),
                "components": button_components
            })
        
    main_card = {
        "type": 17,
        "id": 1,
        "components": card_components
    }
    if color is not None:
        main_card["accent_color"] = color
        
    return main_card

async def send_v2_message(bot, channel_id: int, components: list, files: list = None, content: str = None):
    """
    Mengirim pesan V2 menggunakan HTTP request mentah.
    """
    route = discord.http.Route('POST', f'/channels/{channel_id}/messages')
    
    payload = {
        "components": components,
        "flags": 32768
    }
    
    if content:
        payload["content"] = content
    
    try:
        if files:
            payload["attachments"] = [{"id": i, "filename": f.filename} for i, f in enumerate(files)]
            multipart = [{'name': 'payload_json', 'value': discord.utils._to_json(payload)}]
            for i, file in enumerate(files):
                multipart.append({
                    'name': f'files[{i}]',
                    'value': file.fp,
                    'filename': file.filename,
                    'content_type': 'application/octet-stream'
                })
            params = discord.http.MultipartParameters(payload=None, multipart=multipart, files=files)
            return await bot.http.send_message(channel_id, params=params)
        else:
            return await bot.http.request(route, json=payload)
    except Exception as e:
        print(f"Failed to send V2 layout: {e}")
        return {"error_msg": str(e)}

async def send_v2_webhook(bot, webhook, components: list, content: str = "", username: str = None, avatar_url: str = None):
    """
    Mengirim pesan V2 melalui webhook.
    """
    payload = {
        "content": content,
        "components": components,
        "flags": 32768
    }
    if username:
        payload["username"] = username
    if avatar_url:
        payload["avatar_url"] = avatar_url
        
    route = discord.http.Route('POST', f'/webhooks/{webhook.id}/{webhook.token}')
    return await bot.http.request(route, json=payload)

async def edit_v2_message(bot, channel_id: int, message_id: int, components: list, files: list = None):
    """
    Mengedit pesan V2 menggunakan HTTP request mentah.
    """
    route = discord.http.Route('PATCH', f'/channels/{channel_id}/messages/{message_id}')
    
    payload = {
        "components": components
    }
    
    try:
        if files:
            return await bot.http.request(route, payload=payload, files=files)
        else:
            return await bot.http.request(route, json=payload)
    except Exception as e:
        print(f"Failed to edit V2 layout: {e}")
        return None
