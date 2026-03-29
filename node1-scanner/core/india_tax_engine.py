"""
India Crypto Tax Engine.
30% flat tax + 1% TDS on every sell transaction.
AUTOMATICALLY sets aside tax from every profitable trade.
Only 69% of profit goes back to capital pool.
FIU-registered exchanges (CoinDCX, WazirX) auto-deduct TDS — we track it.
Foreign exchanges (Binance, Bybit) — user must pay TDS manually quarterly.
"""
import os
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass
from latency.base_methods import TieredCache, ConnectionPool
from database.supabase_client import SupabaseClient
import structlog

logger = structlog.get_logger()

TAX_RATE = 0.30       # 30% flat
TDS_RATE = 0.01       # 1% TDS on sell value (Section 194S)
USD_INR_DEFAULT = 84.0  # Fallback rate

# FIU-registered exchanges auto-deduct TDS
FIU_EXCHANGES = {"coindcx", "wazirx", "zebpay", "unocoin"}


@dataclass
class TaxCalculation:
    gross_profit_usdc: float
    gross_profit_inr: float
    tax_30pct_inr: float
    tds_1pct_inr: float           # Paid automatically by FIU exchange
    tds_to_pay_manually_inr: float  # For non-FIU exchanges
    net_tax_inr: float             # 30% - TDS credit
    amount_reserved_usdc: float    # Set aside (never reinvested)
    amount_reinvested_usdc: float  # 69% back to capital pool
    financial_year: str


class IndiaTaxEngine:

    def __init__(self, cache: TieredCache, db: SupabaseClient):
        self._cache = cache
        self._db = db

    async def on_trade_closed(
        self,
        trade_id: str,
        strategy_id: str,
        pnl_usdc: float,
        exchange: str,
        asset: str,
        gross_sell_value_usdc: float,
    ) -> TaxCalculation:
        """
        Called when any trade closes.
        Calculates tax, reserves it, returns reinvestable amount.
        Always called even for losses (to track loss offsets).
        """
        usd_inr = await self._get_usd_inr_rate()
        fy = self._get_financial_year()

        if pnl_usdc <= 0:
            # Loss — track for potential same-asset offset
            await self._log_tax_event(
                trade_id=trade_id,
                event_type="LOSS",
                pnl_usdc=pnl_usdc,
                exchange=exchange,
                asset=asset,
                fy=fy,
                tax_calc=None,
            )
            # No money to set aside — full loss is already absorbed
            return TaxCalculation(
                gross_profit_usdc=pnl_usdc,
                gross_profit_inr=pnl_usdc * usd_inr,
                tax_30pct_inr=0,
                tds_1pct_inr=0,
                tds_to_pay_manually_inr=0,
                net_tax_inr=0,
                amount_reserved_usdc=0,
                amount_reinvested_usdc=pnl_usdc,  # The loss itself
                financial_year=fy,
            )

        # Profitable trade
        profit_inr = pnl_usdc * usd_inr
        tax_30 = profit_inr * TAX_RATE

        # TDS: 1% on gross sell value (not just profit)
        gross_sell_inr = gross_sell_value_usdc * usd_inr
        tds_total = gross_sell_inr * TDS_RATE

        # FIU exchanges deduct TDS automatically (credit against our tax bill)
        tds_auto_deducted = tds_total if exchange.lower() in FIU_EXCHANGES else 0
        tds_manual = tds_total if exchange.lower() not in FIU_EXCHANGES else 0

        # Net tax after TDS credit
        net_tax = max(0, tax_30 - tds_auto_deducted)
        net_tax_usdc = net_tax / usd_inr

        # Reinvestable = profit - tax reserved
        reinvestable = pnl_usdc - net_tax_usdc

        calc = TaxCalculation(
            gross_profit_usdc=pnl_usdc,
            gross_profit_inr=profit_inr,
            tax_30pct_inr=tax_30,
            tds_1pct_inr=tds_total,
            tds_to_pay_manually_inr=tds_manual,
            net_tax_inr=net_tax,
            amount_reserved_usdc=net_tax_usdc,
            amount_reinvested_usdc=reinvestable,
            financial_year=fy,
        )

        # Update tax reserve in cache
        current_reserve = await self._cache.get("tax:reserve_usdc") or 0.0
        new_reserve = current_reserve + net_tax_usdc
        await self._cache.set("tax:reserve_usdc", new_reserve)

        # Update capital pool (only reinvestable portion)
        current_capital = await self._cache.get("capital:current_usdc") or 0.0
        await self._cache.set("capital:current_usdc", current_capital + reinvestable)

        # Log to Supabase
        await self._log_tax_event(trade_id, "GAIN", pnl_usdc, exchange, asset, fy, calc, usd_inr)

        logger.info("tax_calculated",
                    profit_usdc=round(pnl_usdc, 2),
                    tax_reserved_usdc=round(net_tax_usdc, 2),
                    reinvested_usdc=round(reinvestable, 2),
                    effective_rate=f"{(net_tax_usdc/pnl_usdc*100):.1f}%")

        return calc

    async def _log_tax_event(
        self, trade_id, event_type, pnl_usdc, exchange, asset, fy, tax_calc, usd_inr=84.0
    ):
        record = {
            "trade_id": trade_id,
            "financial_year": fy,
            "event_type": event_type,
            "asset": asset,
            "exchange": exchange,
            "gross_profit_usdc": pnl_usdc,
            "usd_inr_rate": usd_inr,
            "created_at": datetime.utcnow().isoformat(),
        }
        if tax_calc:
            record.update({
                "gross_profit_inr": tax_calc.gross_profit_inr,
                "tax_30pct_inr": tax_calc.tax_30pct_inr,
                "tds_1pct_inr": tax_calc.tds_1pct_inr,
                "net_tax_to_pay_inr": tax_calc.net_tax_inr,
                "amount_reserved_usdc": tax_calc.amount_reserved_usdc,
                "amount_reinvested_usdc": tax_calc.amount_reinvested_usdc,
            })
        try:
            self._db.table("tax_events").insert(record).execute()
        except Exception as e:
            logger.warning("tax_log_error", error=str(e))

    async def _get_usd_inr_rate(self) -> float:
        """Get live USD/INR rate. Falls back to 84.0."""
        cached = await self._cache.get("forex:usd_inr")
        if cached:
            return cached
        try:
            session = await ConnectionPool.get()
            resp = await session.get(
                "https://api.exchangerate-api.com/v4/latest/USD",
                timeout=3
            )
            rate = resp.json().get("rates", {}).get("INR", USD_INR_DEFAULT)
            await self._cache.set("forex:usd_inr", rate)
            return rate
        except Exception:
            return USD_INR_DEFAULT

    def _get_financial_year(self) -> str:
        """India FY: April 1 to March 31."""
        today = date.today()
        if today.month >= 4:
            return f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            return f"{today.year - 1}-{str(today.year)[-2:]}"

    async def get_tax_summary(self) -> dict:
        """Summary for dashboard display."""
        fy = self._get_financial_year()
        try:
            result = self._db.table("tax_events").select("*").eq(
                "financial_year", fy
            ).execute()
            events = result.data or []
            gains = [e for e in events if e.get("event_type") == "GAIN"]
            losses = [e for e in events if e.get("event_type") == "LOSS"]
            total_gain_inr = sum(e.get("gross_profit_inr", 0) for e in gains)
            total_loss_inr = sum(abs(e.get("gross_profit_inr", 0)) for e in losses)
            tax_due_inr = sum(e.get("net_tax_to_pay_inr", 0) for e in gains)
            reserved_usdc = await self._cache.get("tax:reserve_usdc") or 0.0
            usd_inr = await self._get_usd_inr_rate()
            dubai_target = float(os.getenv("DUBAI_MILESTONE_USDC", 50000))
            current_capital = await self._cache.get("capital:current_usdc") or 0.0
            return {
                "financial_year": fy,
                "total_gains_inr": total_gain_inr,
                "total_losses_inr": total_loss_inr,
                "net_taxable_inr": total_gain_inr - total_loss_inr,
                "tax_due_inr": tax_due_inr,
                "reserved_usdc": reserved_usdc,
                "reserved_inr": reserved_usdc * usd_inr,
                "dubai_target_usdc": dubai_target,
                "dubai_progress_pct": min(100, current_capital / dubai_target * 100) if dubai_target > 0 else 0,
            }
        except Exception as e:
            logger.error("tax_summary_error", error=str(e))
            return {}
