class Entry:
    """
    Represents a diary entry.
    
    Attributes:
        id (int): Unique identifier of the entry.
        title (str): Entry title (first line of content or user-defined).
        content (str): Decrypted plain text or Markdown content.
        created_at (str): ISO-formatted creation timestamp.
        updated_at (str): ISO-formatted last update timestamp.
        tags (list[str]): List of tags associated with this entry.
        images (list[tuple]): List of images in format (uuid, original_name, decrypted_bytes, b64).
        category (str): Optional category for the entry.
    """
    def __init__(self, id, title, content, created_at, updated_at, tags=None, images=None, category=None):
        self.id = id
        self.title = title
        self.content = content
        self.created_at = created_at
        self.updated_at = updated_at
        self.tags = tags or []
        self.images = images or []  # Each image: (uuid, original_name, decrypted_bytes, base64_str)
        self.category = category

    def add_tag(self, tag):
        """Add a new tag if not already present."""
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag):
        """Remove a tag if it exists."""
        if tag in self.tags:
            self.tags.remove(tag)

    def add_image(self, uuid, original_name, decrypted_bytes, b64_data):
        """
        Add an image to the entry.
        
        Args:
            uuid (str): Unique identifier for the encrypted image file.
            original_name (str): Original file name.
            decrypted_bytes (bytes): Decrypted image bytes.
            b64_data (str): Base64-encoded string for HTML preview.
        """
        self.images.append((uuid, original_name, decrypted_bytes, b64_data))

    def remove_image(self, uuid):
        """Remove an image by its UUID."""
        self.images = [img for img in self.images if img[0] != uuid]

    def get_image_uuids(self):
        """Return a list of image UUIDs."""
        return [img[0] for img in self.images]

    def get_image_b64(self, uuid):
        """Return the Base64 string of a specific image."""
        for img in self.images:
            if img[0] == uuid:
                return img[3]
        return None
