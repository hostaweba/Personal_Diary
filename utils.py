import os
import io
from PIL import Image
import uuid

DATA_DIR = "Data/images"
os.makedirs(DATA_DIR, exist_ok=True)

def encrypt_image_to_file(crypto, original_path):
    """
    Encrypt an image file and save it to the DATA_DIR.
    Returns a tuple of (UUID without .enc, original filename).
    """
    with open(original_path, "rb") as f:
        data = f.read()

    encrypted = crypto.encrypt(data)
    # Generate a unique filename with .enc
    filename = f"{uuid.uuid4()}.enc"
    path = os.path.join(DATA_DIR, filename)
    with open(path, "wb") as f:
        f.write(encrypted)

    original_name = os.path.basename(original_path)
    # Return the UUID without the .enc extension
    return filename[:-4], original_name


def decrypt_image_from_file(crypto, uuid):
    """
    Decrypt an image using its UUID.
    The .enc extension is added here; the caller should provide only the UUID.
    """
    path = os.path.join(DATA_DIR, f"{uuid}.enc")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Encrypted image not found: {path}")
    
    with open(path, "rb") as f:
        encrypted_data = f.read()
    
    return crypto.decrypt(encrypted_data)


def make_thumbnail(img_bytes, max_size=300):
    """
    Generate a thumbnail from raw image bytes.
    Maintains aspect ratio and returns PNG bytes.
    """
    img = Image.open(io.BytesIO(img_bytes))
    img.thumbnail((max_size, max_size))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
