"""
BaseMarketAdapter — interface that all exchange adapters implement.
Scanner calls get_all_markets() on each adapter, gets list[UnifiedMarket].
"""
from abc import ABC, abstractmethod
from typing import List
from ingestion.market_normalizer import UnifiedMarket


class BaseMarketAdapter(ABC):
    """
    Each exchange gets its own adapter class.
    All adapters output UnifiedMarket objects.
    Scanner never knows which exchange a market came from — just reads UnifiedMarket.
    """

    @property
    @abstractmethod
    def exchange_name(self) -> str:
        """Return exchange name string, e.g. 'binance'"""
        pass

    @abstractmethod
    async def fetch_markets(self) -> List[UnifiedMarket]:
        """
        Fetch all actively traded markets from this exchange.
        Returns normalized UnifiedMarket list.
        Must complete in < 500ms.
        """
        pass

    @abstractmethod
    async def get_ticker(self, symbol: str) -> UnifiedMarket:
        """Get single market data. Used by strategies for real-time price."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Return True if exchange API is responding correctly."""
        pass
