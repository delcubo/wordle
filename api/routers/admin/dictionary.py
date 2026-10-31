"""Админка: словарь: исключённые и добавленные слова (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import (
    canonical_word,
    is_valid_word,
    register_added_word,
    SUPPORTED_LENGTHS,
    unregister_added_word,
)
from api.schemas import AddedWordCreateRequest, AddedWordOut, ExcludedWordCreateRequest, ExcludedWordOut

router = APIRouter()


@router.get("/dictionary/excluded", response_model=list[ExcludedWordOut])
async def get_excluded_words(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    words = await crud.list_excluded_words(session)
    return [ExcludedWordOut(id=w.id, word=w.word, excluded_at=str(w.excluded_at)) for w in words]

@router.post("/dictionary/excluded", response_model=ExcludedWordOut)
async def add_excluded_word(
    payload: ExcludedWordCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Исключить слово из выбора будущих слов дня (см. обсуждение источника
    словаря — способ точечно убирать странные/архаичные находки по факту игры).
    На уже назначенные слова (в т.ч. сегодняшнее) и на проверку вводимых
    попыток не влияет — см. ExcludedWord."""
    word = payload.word.strip().lower()
    if len(word) not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5, 6 или 7 букв")
    canonical = canonical_word(word) or word  # приводим е/ё к варианту из словаря, если слово там есть
    excluded = await crud.exclude_word(session, canonical)
    return ExcludedWordOut(id=excluded.id, word=excluded.word, excluded_at=str(excluded.excluded_at))

@router.delete("/dictionary/excluded/{excluded_id}")
async def remove_excluded_word(excluded_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    ok = await crud.unexclude_word(session, excluded_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Не найдено")
    return {"ok": True}

@router.get("/dictionary/added", response_model=list[AddedWordOut])
async def get_added_words(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    words = await crud.list_added_words(session)
    return [AddedWordOut(id=w.id, word=w.word, added_at=str(w.added_at)) for w in words]

@router.post("/dictionary/added", response_model=AddedWordOut)
async def add_added_word(
    payload: AddedWordCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Добавить слово, отсутствующее в словаре, но обнаруженное по факту игры
    (существительное в именительном падеже, 5 букв) — сразу становится и
    валидной попыткой, и кандидатом на будущее слово дня, без деплоя (см.
    AddedWord и dictionary.register_added_word)."""
    word = payload.word.strip().lower()
    if len(word) not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5, 6 или 7 букв")
    if not all("а" <= ch <= "я" or ch == "ё" for ch in word):
        raise HTTPException(status_code=400, detail="Слово должно состоять только из русских букв")
    if is_valid_word(word):
        raise HTTPException(status_code=400, detail="Это слово уже есть в словаре")
    added = await crud.add_word(session, word)
    register_added_word(added.word)
    return AddedWordOut(id=added.id, word=added.word, added_at=str(added.added_at))

@router.delete("/dictionary/added/{added_id}")
async def remove_added_word(added_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    word = await crud.remove_added_word(session, added_id)
    if word is None:
        raise HTTPException(status_code=404, detail="Не найдено")
    unregister_added_word(word)
    return {"ok": True}
