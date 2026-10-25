"""Safe connectivity checks for the OmniDimension SDK."""

from omnidimension import Client


class OmniDimensionCredentialsMissingError(Exception):
    """Raised when no OmniDimension API key is configured."""


class OmniDimensionConnectionError(Exception):
    """Raised when the SDK cannot complete its connectivity check."""


class OmniDimensionService:
    """Small service wrapper around the OmniDimension SDK."""

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def verify_connection(self) -> bool:
        """Return true when listing agents succeeds, without exposing agent data."""
        if not self._api_key or not self._api_key.strip():
            raise OmniDimensionCredentialsMissingError

        try:
            self.create_client().agent.list()
        except Exception:
            # SDK exceptions can contain credentials or provider response data.
            raise OmniDimensionConnectionError from None

        return True

    def create_client(self) -> Client:
        """Construct an authenticated SDK client after checking credentials."""
        if not self._api_key or not self._api_key.strip():
            raise OmniDimensionCredentialsMissingError
        try:
            return Client(self._api_key)
        except Exception:
            raise OmniDimensionConnectionError from None


from typing import Any

class OmniDimensionDispatchProvider:
    """Thin adapter over verified methods in the installed OmniDimension SDK."""

    def __init__(self, api_key: str | None):
        self._client = OmniDimensionService(api_key).create_client()

    def get_agent(self, agent_id: int) -> Any:
        return self._client.agent.get(agent_id)

    def dispatch_call(self, agent_id: int, to_number: str, call_context: dict[str, Any]) -> Any:
        return self._client.call.dispatch_call(
            agent_id=agent_id,
            to_number=to_number,
            call_context=call_context,
        )


