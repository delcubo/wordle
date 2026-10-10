"""
Уведомления админу в Telegram (см. пункт бэклога): когда игрок заканчивает
партию в розыгрыше с включённой опцией notify_admin, в личку админу уходит тот
же текст отчёта, что игрок копирует из попапа (api/report.py), плюс строка со
временем и порядковым номером.

Токен бота и chat_id берутся из переменных окружения TELEGRAM_BOT_TOKEN и
TELEGRAM_CHAT_ID; пока они не заданы — отправка тихо отключена. Отправка идёт
в фоне и никогда не мешает игре: любая ошибка только пишется в лог (без токена).
"""
import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger("wordle.notify")

_background_tasks: set[asyncio.Task] = set()


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _post_message(text: str) -> tuple[bool, str]:
    """Синхронный вызов Bot API (запускается в потоке). Возвращает (успех, пояснение)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False, "Не заданы TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
    body = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return (200 <= response.status < 300), f"HTTP {response.status}"
    except urllib.error.HTTPError as e:
        # тело ответа Telegram объясняет причину (неверный токен, бот не запущен и т.п.)
        try:
            description = json.loads(e.read().decode("utf-8")).get("description", "")
        except Exception:
            description = ""
        return False, f"Telegram ответил {e.code}: {description}".strip()
    except Exception as e:  # сеть/таймаут — токен в сообщение не попадает
        return False, f"Не удалось связаться с Telegram ({type(e).__name__})"


async def send_admin_message(text: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_post_message, text)


def notify_admin_in_background(text: str) -> None:
    """Отправка "выстрелил и забыл": запрос игрока не ждёт Telegram и не падает
    из-за него."""
    if not is_configured():
        return

    async def _run() -> None:
        ok, detail = await send_admin_message(text)
        if not ok:
            logger.warning("Уведомление админу в Telegram не отправлено: %s", detail)

    task = asyncio.get_running_loop().create_task(_run())
    _background_tasks.add(task)  # иначе задачу может съесть сборщик мусора до завершения
    task.add_done_callback(_background_tasks.discard)
