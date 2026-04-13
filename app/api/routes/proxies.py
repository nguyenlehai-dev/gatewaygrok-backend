from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.proxy import Proxy
from app.schemas.proxy import ProxyCreate, ProxyRead, ProxyUpdate

router = APIRouter()


@router.get("", response_model=list[ProxyRead])
def list_proxies(db: Session = Depends(db_session)):
    return db.query(Proxy).order_by(Proxy.created_at.desc()).all()


@router.post("", response_model=ProxyRead, status_code=status.HTTP_201_CREATED)
def create_proxy(payload: ProxyCreate, db: Session = Depends(db_session)):
    proxy = Proxy(**payload.model_dump())
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.put("/{proxy_id}", response_model=ProxyRead)
def update_proxy(proxy_id: str, payload: ProxyUpdate, db: Session = Depends(db_session)):
    proxy = db.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(proxy, key, value)
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proxy(proxy_id: str, db: Session = Depends(db_session)):
    proxy = db.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    db.delete(proxy)
    db.commit()
