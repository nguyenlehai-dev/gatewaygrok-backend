from pydantic import BaseModel


class ProfileAssetRead(BaseModel):
    profile_id: str
    original_filename: str
    stored_path: str
    content_type: str | None = None
    size: int
