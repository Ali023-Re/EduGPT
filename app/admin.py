from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from models import MethodicEntry
from auth import get_current_user  # проверка сессии (Redis)

# роутер для всех /documents эндпоинтов
router = APIRouter(prefix="/documents", tags=["Admin"])


# получить список документов (поиск + пагинация + сортировка)
@router.get("")
def get_documents(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),

    search: str = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "id",
    order: str = "desc",
):
    query = db.query(MethodicEntry)

    # поиск по названию
    if search:
        query = query.filter(MethodicEntry.source_title.ilike(f"%{search}%"))

    # сортировка
    sort_column = getattr(MethodicEntry, sort_by, MethodicEntry.id)
    if order == "desc":
        sort_column = sort_column.desc()

    query = query.order_by(sort_column)

    total = query.count()

    # пагинация
    items = query.offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [
            {
                "id": m.id,
                "name": m.source_title,
                "author": m.author,
                "size": len(m.methodic_text) if m.methodic_text else 0,
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "limit": limit
    }


# загрузка документа
@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    content = await file.read()

    # сохраняем как текст
    doc = MethodicEntry(
        source_title=file.filename,
        author="unknown",
        methodic_text=content.decode(errors="ignore")
    )

    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {"id": doc.id}


# открыть документ
@router.get("/{doc_id}")
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    m = db.query(MethodicEntry).filter_by(id=doc_id).first()

    if not m:
        raise HTTPException(404)

    return {
        "id": m.id,
        "name": m.source_title,
        "author": m.author,
        "text": m.methodic_text
    }


# редактировать документ
@router.patch("/{doc_id}")
async def update_document(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    data = await request.json()

    m = db.query(MethodicEntry).filter_by(id=doc_id).first()

    if not m:
        raise HTTPException(404)


    if "name" in data:
        m.source_title = data["name"]

    if "author" in data:
        m.author = data["author"]

    if "text" in data:
        m.methodic_text = data["text"]

    db.commit()

    return {"message": "updated"}


# копировать документ
@router.post("/{doc_id}/copy")
def copy_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    m = db.query(MethodicEntry).filter_by(id=doc_id).first()

    if not m:
        raise HTTPException(404)

    new_doc = MethodicEntry(
        source_title=m.source_title + " (копия)",
        author=m.author,
        methodic_text=m.methodic_text
    )

    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return {"id": new_doc.id}


# удалить один документ
@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    m = db.query(MethodicEntry).filter_by(id=doc_id).first()

    if not m:
        raise HTTPException(404)

    db.delete(m)
    db.commit()

    return {"message": "deleted"}


# удалить несколько документов (bulk)
@router.delete("")
async def delete_multiple_documents(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user)
):
    data = await request.json()
    ids = data.get("ids", [])

    if not ids:
        raise HTTPException(400, "No IDs provided")

    docs = db.query(MethodicEntry).filter(MethodicEntry.id.in_(ids)).all()

    deleted = 0

    for doc in docs:
        db.delete(doc)
        deleted += 1

    db.commit()

    return {"deleted": deleted}