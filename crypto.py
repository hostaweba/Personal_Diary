from cryptography.fernet import Fernet
from argon2.low_level import hash_secret_raw, Type
import os
import base64

class CryptoManager:
    """
    Handles encryption and decryption of diary content and images
    using a master password and a salt. Key derivation uses Argon2id.
    """
    def __init__(self, master_password: str, salt: bytes = None):
        # Use explicit 'is not None' to prevent accidental overwriting of valid empty/falsy salts
        self.salt = salt if salt is not None else os.urandom(16)
        
        # Derive the key and immediately initialize Fernet.
        # Do NOT store the derived key as an instance variable (e.g., self.key)
        # to minimize its footprint in RAM and reduce memory scraping risks.
        fernet_key = self.derive_key(master_password)
        self.fernet = Fernet(fernet_key)
        
        # Explicitly delete local variables containing sensitive data
        del fernet_key
        del master_password

    def derive_key(self, password: str) -> bytes:
        """
        Derive a 32-byte key from the master password using Argon2id.

        Args:
            password (str): Master password.

        Returns:
            bytes: Base64-encoded 32-byte key for Fernet.
        """
        key_bytes = hash_secret_raw(
            secret=password.encode('utf-8'),
            salt=self.salt,
            time_cost=3,       # Number of iterations
            memory_cost=65536, # Memory cost in KiB (64 MB)
            parallelism=4,     # Parallel threads
            hash_len=32,       # Desired key length
            type=Type.ID       # Argon2id variant (recommended)
        )
        
        encoded_key = base64.urlsafe_b64encode(key_bytes)
        
        # Clear raw bytes from memory immediately after encoding
        del key_bytes
        
        return encoded_key

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt data using the derived key.

        Args:
            plaintext (bytes): Data to encrypt.

        Returns:
            bytes: Encrypted data.
        """
        return self.fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """
        Decrypt data using the derived key.

        Args:
            ciphertext (bytes): Encrypted data.

        Returns:
            bytes: Decrypted plaintext.
        """
        return self.fernet.decrypt(ciphertext)
