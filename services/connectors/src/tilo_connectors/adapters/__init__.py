"""tilo_connectors.adapters — Gmail, Drive and Calendar adapters (FR-CON-04, FR-CON-05, FR-CAL-08).

Only these modules and `tokens.py` call `access_token_for_adapter` (SEC-02).
"""

from ._google import side_effect_marker as side_effect_marker
from ._transport import MAX_ATTEMPTS as MAX_ATTEMPTS
from ._transport import AdapterError as AdapterError
from ._transport import ApiResponse as ApiResponse
from ._transport import ArtifactSource as ArtifactSource
from ._transport import FileTooLarge as FileTooLarge
from ._transport import NotPicked as NotPicked
from ._transport import ProviderUnavailable as ProviderUnavailable
from ._transport import RateLimited as RateLimited
from ._transport import SideEffectRefused as SideEffectRefused
from ._transport import SyncTokenExpired as SyncTokenExpired
from ._transport import Transport as Transport
from ._transport import TransportError as TransportError
from .calendar import CALENDAR_API as CALENDAR_API
from .calendar import CalendarAdapter as CalendarAdapter
from .drive import DRIVE_API as DRIVE_API
from .drive import DRIVE_UPLOAD_API as DRIVE_UPLOAD_API
from .drive import MAX_DOWNLOAD_BYTES as MAX_DOWNLOAD_BYTES
from .drive import DriveAdapter as DriveAdapter
from .drive import InMemoryPicks as InMemoryPicks
from .gmail import BLOCKED_ATTACHMENT_EXTENSIONS as BLOCKED_ATTACHMENT_EXTENSIONS
from .gmail import GMAIL_API as GMAIL_API
from .gmail import MAX_ATTACHMENT_BYTES as MAX_ATTACHMENT_BYTES
from .gmail import GmailAdapter as GmailAdapter
