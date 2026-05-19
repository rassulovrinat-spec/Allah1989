import hashlib
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"pbkdf2:{salt}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, stored_key = stored.split(":")
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
        return key.hex() == stored_key
    except Exception:
        return False


def make_token(user_id: int, username: str, role: str) -> str:
    return serializer.dumps({"user_id": user_id, "username": username, "role": role})


def decode_token(token: str):
    try:
        return serializer.loads(token, max_age=86400 * 7)
    except BadSignature:
        return None
