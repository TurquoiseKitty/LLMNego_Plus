"""
utility.py — Utility functions for vending machine negotiation agents.

Each utility is an object with three interfaces:
  - .name          : str  — unique identifier
  - .verbal        : str  — natural-language description for LLM system prompts
  - .verbal_short  : str  — condensed description for smaller / less capable models
  - .__call__(...)        — numeric evaluation of the utility given a deal

To add a new utility, subclass SupplierUtility or MerchantUtility, override
name / verbal / verbal_short / __call__, and register the instance in
SUPPLIER_UTILITIES or MERCHANT_UTILITIES.

Assumption: purchase quantity always equals the minimum required quantity.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Deal representation
# ---------------------------------------------------------------------------

@dataclass
class DealItem:
    """A single agreed line item between merchant and supplier."""
    product_name:    str
    category:        str
    production_cost: float   # public — supplier's raw manufacturing cost per unit
    market_price:    float   # public — retail market price per unit
    deal_price:      float   # negotiated — price paid by merchant to supplier per unit
    quantity:        int     # agreed units (always equals min_required in our setup)


# ===========================================================================
# SUPPLIER UTILITIES
# ===========================================================================

class SupplierUtility:
    """
    Base class for supplier utility functions.

    Subclasses override name, verbal, verbal_short, and __call__.

    __call__ signature:
      deal_items     : list[DealItem]
      internal_costs : dict[str, float]  — category -> per-unit fulfilment cost (private)
    """

    name:         str = ""
    verbal:       str = ""
    verbal_short: str = ""

    def __call__(
        self,
        deal_items:     list[DealItem],
        internal_costs: dict[str, float],
    ) -> float:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class SupplierNetProfit(SupplierUtility):
    """Supplier utility = net profit = sum of (deal_price - production_cost - internal_cost) * quantity."""

    name = "supplier_net_profit"

    verbal = """\
UTILITY FUNCTION — Supplier

Your utility is your total net profit from the deal.

Definitions:
  - deal_price      : the price per unit you charge the merchant
  - production_cost : the publicly known manufacturing cost per unit
  - internal_cost   : your private per-unit fulfilment cost (shipping, packaging,
                      quality checks); varies by product category; the merchant
                      does not know this value

For each product line:
  unit_profit = deal_price - production_cost - internal_cost

Your total utility:
  U = sum of (unit_profit × quantity) across all product lines

U = 0 means you break even after all costs.
U > 0 means you are profitable.
U < 0 means you are losing money on this deal.

If the deal fails, your utility is also 0, as you have no profit but also no costs.\
"""

    verbal_short = """\
UTILITY FUNCTION — Supplier

Your utility is your net profit:
  U = sum of (deal_price - production_cost - internal_cost) × quantity

If the deal fails, your utility is 0.\
"""

    def __call__(
        self,
        deal_items:     list[DealItem],
        internal_costs: dict[str, float],
    ) -> float:
        return sum(
            (item.deal_price - item.production_cost - internal_costs.get(item.category, 0.0))
            * item.quantity
            for item in deal_items
        )


# ===========================================================================
# MERCHANT UTILITIES
# ===========================================================================

class MerchantUtility:
    """
    Base class for merchant utility functions.

    Subclasses override name, verbal, verbal_short, and __call__.

    __call__ signature:
      deal_items     : list[DealItem]
      internal_costs : dict[str, float]  — category -> per-unit selling cost (private)
    """

    name:         str = ""
    verbal:       str = ""
    verbal_short: str = ""

    def __call__(
        self,
        deal_items:     list[DealItem],
        internal_costs: dict[str, float],
    ) -> float:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class MerchantNetProfit(MerchantUtility):
    """Merchant utility = net profit = sum of (market_price - deal_price - internal_cost) * quantity."""

    name = "merchant_net_profit"

    verbal = """\
UTILITY FUNCTION — Merchant

Your utility is your total net profit from selling the purchased products.

Definitions:
  - market_price  : the publicly known retail price at which you sell each unit
  - deal_price    : the price per unit you pay the supplier (what you negotiate)
  - internal_cost : your private per-unit selling overhead (restocking labour,
                    location rent share, shrinkage); varies by product category;
                    the supplier does not know this value
  - quantity      : always equal to the minimum required amount for each product

For each product line:
  unit_profit = market_price - deal_price - internal_cost

Your total utility:
  U = sum of (unit_profit × quantity) across all product lines

U = 0 means you break even after all costs.
U > 0 means the deal is profitable for you.
U < 0 means the deal costs you money.

If the deal fails, your utility is also 0, as you have no profit but also no costs.\
"""

    verbal_short = """\
UTILITY FUNCTION — Merchant

Your utility is your net profit:
  U = sum of (market_price - deal_price - internal_cost) × quantity

If the deal fails, your utility is 0.\
"""

    def __call__(
        self,
        deal_items:     list[DealItem],
        internal_costs: dict[str, float],
    ) -> float:
        return sum(
            (item.market_price - item.deal_price - internal_costs.get(item.category, 0.0))
            * item.quantity
            for item in deal_items
        )


# ===========================================================================
# Registries — add new instances here when extending
# ===========================================================================

SUPPLIER_UTILITIES: dict[str, SupplierUtility] = {
    u.name: u for u in [
        SupplierNetProfit(),
    ]
}

MERCHANT_UTILITIES: dict[str, MerchantUtility] = {
    u.name: u for u in [
        MerchantNetProfit(),
    ]
}

# Default singletons for direct import
supplier_utility: SupplierUtility = SUPPLIER_UTILITIES["supplier_net_profit"]
merchant_utility: MerchantUtility = MERCHANT_UTILITIES["merchant_net_profit"]