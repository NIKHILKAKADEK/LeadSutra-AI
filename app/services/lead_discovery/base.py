"""Abstract base class for business discovery providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.lead import BusinessLead


class BaseBusinessDiscoveryProvider(ABC):
    """Interface that every business discovery provider must implement.

    LeadSutra uses a provider-agnostic discovery layer so that different
    backends (Google Places, Foursquare, etc.) can be swapped or chained
    without changing downstream code.
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        location: str,
        limit: int | None = 20,
    ) -> list[BusinessLead]:
        """Search for businesses matching *query* near *location*.

        Parameters
        ----------
        query:
            Business type or keyword (e.g. ``"cafe"``).
        location:
            City / region string (e.g. ``"Nashik, Maharashtra"``).
        limit:
            Maximum number of results to return.  Providers may return
            fewer results when the API does not support this parameter
            directly.

        Returns
        -------
        list[BusinessLead]
            Normalised lead objects.  Never ``None``; returns an empty
            list when no results are found.

        Raises
        ------
        LeadDiscoveryError
            Or any of its sub-classes on unrecoverable API failures.
        """
