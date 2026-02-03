from cryptography.fernet import Fernet
from config.settings import ENCRYPTION_KEY

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY must be set in .env")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())

def encrypt_text(text: str) -> str:
    """Encrypts a plaintext string."""
    return cipher_suite.encrypt(text.encode()).decode()

def decrypt_text(encrypted_text: str) -> str:
    """Decrypts an encrypted string."""
    return cipher_suite.decrypt(encrypted_text.encode()).decode()
