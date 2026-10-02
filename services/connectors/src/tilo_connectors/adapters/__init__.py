"""tilo_connectors.adapters — Gmail and Drive adapters (FR-CON-04, FR-CON-05). tests/API_FR_CON_04_05.md.

Only these modules and `tokens.py` call `access_token_for_adapter` (SEC-02).
"""

from ._transport import MAX_ATTEMPTS as MAX_ATTEMPTS
from ._transport import AdapterError as AdapterError
from ._transport import ApiResponse as ApiResponse
from ._transport import ArtifactSource as ArtifactSource
from ._transport import FileTooLarge as FileTooLarge
from ._transport import NotPicked as NotPicked
from ._transport import ProviderUnavailable as ProviderUnavailable
from ._transport import RateLimited as RateLimited
from ._transport import SideEffectRefused as SideEffectRefused
from ._transport import Transport as Transport
from ._transport import TransportError as TransportError
