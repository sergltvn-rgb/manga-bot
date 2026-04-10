from aiogram.types import Message
import json

message_json = {
    "message_id": 1,
    "date": 1234567890,
    "chat": {"id": 1, "type": "private"},
    "text": "https://example.com/test",
    "entities": [{"type": "url", "offset": 0, "length": 24}]
}
msg = Message.model_validate(message_json)
print(f"text: {repr(msg.text)}")
print(f"html_text: {repr(msg.html_text)}")

message_json2 = {
    "message_id": 2,
    "date": 1234567890,
    "chat": {"id": 1, "type": "private"},
    "text": "1 Глава | (1 часть) (2часть)",
    "entities": [
        {"type": "text_link", "offset": 10, "length": 9, "url": "https://example.com/1"},
        {"type": "text_link", "offset": 20, "length": 8, "url": "https://example.com/2"}
    ]
}
msg2 = Message.model_validate(message_json2)
print(f"text2: {repr(msg2.text)}")
print(f"html_text2: {repr(msg2.html_text)}")
