from cryptography.fernet import Fernet
from argon2.low_level import hash_secret_raw, Type
import os, base64

class CryptoManager:
    """
    Handles encryption and decryption of diary content and images
    using a master password and a salt. Key derivation uses Argon2id.
    """
    def __init__(self, master_password: str, salt: bytes = None):
        # Generate a new random salt if not provided
        self.salt = salt or os.urandom(16)
        # Derive a symmetric encryption key from the password
        self.key = self.derive_key(master_password)
        # Initialize Fernet for encryption/decryption
        self.fernet = Fernet(self.key)

    def derive_key(self, password: str) -> bytes:
        """
        Derive a 32-byte key from the master password using Argon2id.

        Args:
            password (str): Master password.

        Returns:
            bytes: Base64-encoded 32-byte key for Fernet.
        """
        key_bytes = hash_secret_raw(
            secret=password.encode(),
            salt=self.salt,
            time_cost=3,       # Number of iterations
            memory_cost=65536, # Memory cost in KiB (64 MB)
            parallelism=4,     # Parallel threads
            hash_len=32,       # Desired key length
            type=Type.ID       # Argon2id variant (recommended)
        )
        return base64.urlsafe_b64encode(key_bytes)

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
