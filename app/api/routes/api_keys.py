from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, ApiKeyUpdate
from app.services.api_key_service import api_key_service

router = APIRouter()


def serialize(record: ApiKey) -> ApiKeyRead:
    return ApiKeyRead(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        rate_limit_per_minute=record.rate_limit_per_minute,
        is_active=record.is_active,
        allowed_categories=api_key_service.parse_categories(record),
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=list[ApiKeyRead])
def list_api_keys(db: Session = Depends(db_session)):
    records = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [serialize(record) for record in records]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(db_session)):
    try:
        record, plain_key = api_key_service.create(
            db,
            name=payload.name,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            allowed_categories=payload.allowed_categories,
            notes=payload.notes,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="API key name already exists")
    serialized = serialize(record)
    return ApiKeyCreated(**serialized.model_dump(), plain_key=plain_key)


@router.put("/{api_key_id}", response_model=ApiKeyRead)
def update_api_key(api_key_id: str, payload: ApiKeyUpdate, db: Session = Depends(db_session)):
    record = db.get(ApiKey, api_key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    data = payload.model_dump(exclude_unset=True)
    if "allowed_categories" in data:
        data["allowed_categories"] = ",".join(data["allowed_categories"])
    for key, value in data.items():
        setattr(record, key, value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize(record)
