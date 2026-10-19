"""Compensate source-revoked SDK writes without deleting concurrent replacements."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound


def guarded_write(client: Any, document: Any, row: dict, write: Callable[[dict], Any], check: Callable[[], Any]) -> Any:
    row = {**row, "publication_nonce": uuid4().hex}
    error = None
    try:
        result = write(row)
    except AlreadyExists:
        raise
    except Exception as exc:
        error, result = exc, None
    try:
        check()  # also after an SDK failure: an acknowledgement may have been lost
    except Exception:
        try:
            found = document.get()
            if found.exists and found.to_dict() == row:
                document.delete(option=client.write_option(last_update_time=found.update_time))
        except (FailedPrecondition, NotFound):
            pass  # a replacement belongs to a different publication
        except Exception:
            raise HTTPException(503, "store_unavailable", headers={"Cache-Control": "no-store"}) from None
        raise
    if error is not None:
        raise HTTPException(503, "store_unavailable", headers={"Cache-Control": "no-store"}) from error
    return result
