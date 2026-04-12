from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Category keys — must match Product.category values in products.py
# ---------------------------------------------------------------------------

BEVERAGE    = "Beverage"
SNACK       = "Snack"
CONVENIENCE = "Convenience"

CATEGORIES = (BEVERAGE, SNACK, CONVENIENCE)


# ---------------------------------------------------------------------------
# Internal cost structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InternalCostStructure:
    """
    Per-category internal cost (in $ per unit).

    For a Merchant this represents additional selling overhead per unit
    (e.g. restocking labour, location rent share, shrinkage).
    For a Supplier this represents additional fulfilment cost per unit
    (e.g. last-mile logistics, packaging, quality-control overhead).

    These values are PRIVATE to each agent and are NOT revealed to the
    counterparty during negotiation.
    """
    beverage:    float
    snack:       float
    convenience: float

    def for_category(self, category: str) -> float:
        if category == BEVERAGE:
            return self.beverage
        if category == SNACK:
            return self.snack
        if category == CONVENIENCE:
            return self.convenience
        raise ValueError(f"Unknown category: {category!r}")

    @property
    def is_uniform(self) -> bool:
        """True when internal cost is the same across all categories."""
        return self.beverage == self.snack == self.convenience


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Agent:
    id:                 str
    name:               str
    description:        str
    internal_costs:     InternalCostStructure
    max_rounds:         int                    # maximum negotiation turns allowed


# ---------------------------------------------------------------------------
# Merchant
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Merchant(_Agent):
    """
    Represents a vending machine operator (buyer).

    The Merchant knows:
      - The public market_price of every product
      - The public production cost of every product
      - Its own internal_costs (private)

    The Merchant's reservation price per unit of product p is:
        market_price(p) - internal_costs.for_category(p.category)

    Any deal price above this reservation price eats into the Merchant's margin.
    """


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Supplier(_Agent):
    """
    Represents a product supplier (seller).

    The Supplier knows:
      - The public market_price of every product
      - The public production cost of every product
      - Its own internal_costs (private)

    The Supplier's reservation price per unit of product p is:
        production_cost(p) + internal_costs.for_category(p.category)

    Any deal price below this reservation price means the supplier ships
    at a loss after fulfilment overhead.
    """


# ===========================================================================
# Merchant types
# ===========================================================================

# ---------------------------------------------------------------------------
# M1 — Budget operator
# Low overhead across the board, uniform cost structure, impatient.
# Runs lean machines in high-footfall commodity locations (stations, schools).
# Accepts thin margins; needs deals closed quickly to minimise admin time.
# ---------------------------------------------------------------------------

BUDGET_MERCHANT = Merchant(
    id="M1",
    name="Budget operator",
    description=(
        "A high-volume, low-overhead vending operator. Machines are placed in "
        "commodity locations (stations, schools). Internal costs are uniformly low "
        "because operations are standardised and labour is minimal. Needs deals "
        "closed fast — long negotiations waste more money than a bad price."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.05,
        snack=0.05,
        convenience=0.05,
    ),
    max_rounds=3,  
)

# ---------------------------------------------------------------------------
# M2 — Premium location operator
# Low beverage/snack overhead, high convenience overhead (security, licensing).
# Moderate patience — will negotiate but has deadlines.
# Runs machines in airports and hotels where convenience items need special
# handling and compliance, driving up per-unit cost for that category.
# ---------------------------------------------------------------------------

PREMIUM_MERCHANT = Merchant(
    id="M2",
    name="Premium location operator",
    description=(
        "Operates vending machines in airports, hotels, and transit hubs. "
        "Beverage and snack handling is efficient, but convenience items "
        "(electronics, medicines) carry high compliance and security overhead. "
        "Willing to negotiate for several rounds to secure favourable unit prices "
        "on high-margin products."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.08,
        snack=0.10,
        convenience=0.45,
    ),
    max_rounds=5,
)

# ---------------------------------------------------------------------------
# M3 — Health & wellness operator
# Medium beverage overhead, low snack overhead (specialised in health snacks),
# negligible convenience overhead. Patient negotiator.
# Focuses on gyms, corporate offices; has strong brand standards and SLAs
# that add cost to beverage sourcing but not to snacks.
# ---------------------------------------------------------------------------

WELLNESS_MERCHANT = Merchant(
    id="M3",
    name="Health & wellness operator",
    description=(
        "Specialises in gyms, sports centres, and corporate wellness programmes. "
        "Snack handling is low-cost due to standardised health-product logistics. "
        "Beverages carry a medium overhead from cold-chain requirements and brand "
        "compliance. Almost never stocks convenience items. Patient negotiator "
        "with clear quality thresholds — willing to walk away."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.18,
        snack=0.06,
        convenience=0.10,
    ),
    max_rounds=6,
)

# ---------------------------------------------------------------------------
# M4 — Hospital & care-site operator
# High overhead across all categories due to hygiene certification, regulated
# product checks, and site access restrictions. Very patient.
# ---------------------------------------------------------------------------

CARE_SITE_MERCHANT = Merchant(
    id="M4",
    name="Hospital & care-site operator",
    description=(
        "Operates machines in hospitals, clinics, and care homes. Every product "
        "category incurs elevated overhead: beverages require nutritional labelling "
        "checks, snacks need allergen audits, and convenience items (sanitiser, "
        "masks, medicines) face strict regulatory review. High internal costs "
        "across the board. Negotiates slowly and carefully."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.20,
        snack=0.22,
        convenience=0.50,
    ),
    max_rounds=8,
)


# ===========================================================================
# Supplier types
# ===========================================================================

# ---------------------------------------------------------------------------
# S1 — Local distributor
# Low fulfilment cost for beverages and snacks (short routes, own fleet),
# high cost for convenience (small batches, specialist sourcing).
# Impatient — small operation, opportunity cost of a stalled deal is high.
# ---------------------------------------------------------------------------

LOCAL_SUPPLIER = Supplier(
    id="S1",
    name="Local distributor",
    description=(
        "A regional distributor with its own delivery fleet covering a tight "
        "geographic area. Beverage and snack fulfilment is cheap due to bulk "
        "routes and proximity. Convenience items are sourced from third parties "
        "in small batches, making them expensive to ship. Impatient: a long "
        "negotiation ties up a sales rep who could be closing other deals."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.04,
        snack=0.05,
        convenience=0.40,
    ),
    max_rounds=3,
)

# ---------------------------------------------------------------------------
# S2 — National wholesaler
# Uniform medium cost across all categories — economies of scale flatten
# differences. Moderate patience; has a structured sales process.
# ---------------------------------------------------------------------------

NATIONAL_SUPPLIER = Supplier(
    id="S2",
    name="National wholesaler",
    description=(
        "A large national wholesaler with centralised warehousing and a "
        "standardised logistics network. Economies of scale mean per-unit "
        "fulfilment costs are moderate and fairly uniform across categories. "
        "Has a formal sales process with account managers — comfortable with "
        "multi-round negotiation but expects structured counter-offers."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.12,
        snack=0.12,
        convenience=0.15,
    ),
    max_rounds=5,
)

# ---------------------------------------------------------------------------
# S3 — Specialist health supplier
# Very low snack fulfilment cost (core competency), medium beverage cost,
# high convenience cost (outside their catalogue). Patient.
# ---------------------------------------------------------------------------

HEALTH_SUPPLIER = Supplier(
    id="S3",
    name="Specialist health supplier",
    description=(
        "Focuses on health foods, protein products, and wellness snacks. "
        "Snack fulfilment is extremely efficient — dedicated cold-press and "
        "dry-goods lines with optimised packing. Beverages are handled but at "
        "higher cost. Convenience items are rarely stocked and expensive to "
        "source and ship. Willing to negotiate patiently to win wellness "
        "accounts that fit their brand."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.15,
        snack=0.03,
        convenience=0.35,
    ),
    max_rounds=7,
)

# ---------------------------------------------------------------------------
# S4 — Medical & compliance supplier
# High cost across beverages and snacks (regulated storage), very high cost
# for convenience (end-to-end compliance chain). Very patient.
# ---------------------------------------------------------------------------

COMPLIANCE_SUPPLIER = Supplier(
    id="S4",
    name="Medical & compliance supplier",
    description=(
        "Specialises in supplying vending machines in regulated environments "
        "(hospitals, care homes, airports). Every shipment undergoes compliance "
        "checks: temperature logging for beverages, allergen certification for "
        "snacks, and full regulatory audit trails for convenience items. Internal "
        "costs are high across all categories. Negotiates slowly and methodically, "
        "expects counterparties to understand and accept the compliance premium."
    ),
    internal_costs=InternalCostStructure(
        beverage=0.22,
        snack=0.25,
        convenience=0.60,
    ),
    max_rounds=8,
)


# ===========================================================================
# Catalogues
# ===========================================================================

ALL_MERCHANTS: tuple[Merchant, ...] = (
    BUDGET_MERCHANT,
    PREMIUM_MERCHANT,
    WELLNESS_MERCHANT,
    CARE_SITE_MERCHANT,
)

ALL_SUPPLIERS: tuple[Supplier, ...] = (
    LOCAL_SUPPLIER,
    NATIONAL_SUPPLIER,
    HEALTH_SUPPLIER,
    COMPLIANCE_SUPPLIER,
)

MERCHANT_BY_ID: dict[str, Merchant] = {m.id: m for m in ALL_MERCHANTS}
SUPPLIER_BY_ID: dict[str, Supplier] = {s.id: s for s in ALL_SUPPLIERS}