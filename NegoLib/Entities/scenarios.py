from dataclasses import dataclass

from NegoLib.Entities.products import (
    Product,
    COLA, SPARKLING_WATER, ORANGE_JUICE, ENERGY_DRINK, ICED_COFFEE, PROTEIN_SHAKE,
    POTATO_CHIPS, CHOCOLATE_BAR, GRANOLA_BAR, MIXED_NUTS, GUMMY_CANDY, PROTEIN_BAR, CRACKERS_WITH_CHEESE,
    HAND_SANITIZER, FACE_MASK, EARPHONES, USB_C_CABLE, PARACETAMOL, CHEWING_GUM, LIP_BALM,
)


@dataclass(frozen=True)
class ProductOrder:
    """A single line item in a scenario: which product and how many units minimum."""
    product: Product
    min_units: int


@dataclass(frozen=True)
class Scenario:
    """
    A negotiation scenario between a Merchant and a Supplier.

    The Merchant wants to stock a vending machine placed at a specific location.
    Each order line specifies the minimum units required to meet demand.
    The Supplier knows the cost; the Merchant knows the market price.
    """
    id: str
    name: str
    location: str
    description: str
    orders: tuple[ProductOrder, ...]

    @property
    def total_min_units(self) -> int:
        return sum(o.min_units for o in self.orders)

    @property
    def merchant_budget_floor(self) -> float:
        """Minimum spend at cost price — lower bound for supplier's ask."""
        return sum(o.product.cost * o.min_units for o in self.orders)

    @property
    def merchant_revenue_ceiling(self) -> float:
        """Maximum revenue if all units sell at market price."""
        return sum(o.product.market_price * o.min_units for o in self.orders)


# ===========================================================================
# Single-item scenarios (S01–S03)
# Designed for studying pure bilateral negotiation with no product-mix
# complexity. Each isolates a different product category and margin profile.
# ===========================================================================

# ---------------------------------------------------------------------------
# Scenario 01 — Street kiosk (single item: Cola)
# Beverage category, very high margin (~80%). The simplest possible
# negotiation: one commodity product, well-known market price, large volume.
# ---------------------------------------------------------------------------

KIOSK_COLA = Scenario(
    id="S01",
    name="Street kiosk — Cola",
    location="Street kiosk",
    description=(
        "A street-level kiosk vending machine restocking its single best-seller: Cola. "
        "The market price is widely known, the product is a commodity, and the margin "
        "is very high. This is the baseline single-item negotiation: volume is the main "
        "lever, and the supplier has little room to hide cost."
    ),
    orders=(
        ProductOrder(COLA, min_units=60),
    ),
)

# ---------------------------------------------------------------------------
# Scenario 02 — Gym entrance (single item: Protein bar)
# Snack category, moderate margin (~63%). Niche product with less price
# transparency than a cola — supplier has more information asymmetry to exploit.
# ---------------------------------------------------------------------------

GYM_PROTEIN_BAR = Scenario(
    id="S02",
    name="Gym entrance — Protein bar",
    location="Gym",
    description=(
        "A vending machine at the entrance of a commercial gym stocking only "
        "protein bars. The product is specialised, market price is less obvious "
        "to the Merchant than for commodity drinks, and the supplier can exploit "
        "moderate information asymmetry around production cost."
    ),
    orders=(
        ProductOrder(PROTEIN_BAR, min_units=40),
    ),
)

# ---------------------------------------------------------------------------
# Scenario 03 — Airport gate (single item: USB-C cable)
# Convenience category, very high margin (~78%). Premium impulse purchase with
# high price variance in the wild — widest negotiation zone of the three.
# ---------------------------------------------------------------------------

AIRPORT_USB_CABLE = Scenario(
    id="S03",
    name="Airport gate — USB-C cable",
    location="Airport",
    description=(
        "A vending machine at an airport departure gate stocking only USB-C "
        "charging cables. Travellers pay a premium when desperate; the market "
        "price is highly variable and the Merchant has weak price anchors. "
        "This creates the widest negotiation zone: both sides have genuine "
        "uncertainty about a fair price."
    ),
    orders=(
        ProductOrder(USB_C_CABLE, min_units=20),
    ),
)


# ===========================================================================
# Multi-item scenarios (S04–S07)
# Representative real-world locations with diverse product mixes.
# ===========================================================================

# ---------------------------------------------------------------------------
# Scenario 04 — Airport transit lounge
# High footfall, low price sensitivity, mixed categories.
# ---------------------------------------------------------------------------

AIRPORT_TRANSIT = Scenario(
    id="S04",
    name="Airport transit lounge",
    location="Airport transit",
    description=(
        "A vending machine in a busy international transit lounge. "
        "Travellers want cold drinks, snacks, and last-minute convenience items "
        "before boarding. Demand is high and price sensitivity is low."
    ),
    orders=(
        ProductOrder(COLA,            min_units=48),
        ProductOrder(SPARKLING_WATER, min_units=36),
        ProductOrder(ENERGY_DRINK,    min_units=24),
        ProductOrder(POTATO_CHIPS,    min_units=30),
        ProductOrder(CHOCOLATE_BAR,   min_units=30),
        ProductOrder(EARPHONES,       min_units=12),
        ProductOrder(USB_C_CABLE,     min_units=10),
        ProductOrder(PARACETAMOL,     min_units=20),
        ProductOrder(CHEWING_GUM,     min_units=40),
    ),
)

# ---------------------------------------------------------------------------
# Scenario 05 — Corporate office lobby
# Monday–Friday crowd, health-conscious, moderate volumes.
# ---------------------------------------------------------------------------

OFFICE_LOBBY = Scenario(
    id="S05",
    name="Corporate office lobby",
    location="Office",
    description=(
        "A vending machine in the lobby of a mid-size tech company. "
        "Employees pass through during work hours seeking light snacks and "
        "caffeinated drinks. Health-conscious product mix preferred."
    ),
    orders=(
        ProductOrder(ICED_COFFEE,     min_units=30),
        ProductOrder(SPARKLING_WATER, min_units=24),
        ProductOrder(PROTEIN_BAR,     min_units=20),
        ProductOrder(GRANOLA_BAR,     min_units=20),
        ProductOrder(MIXED_NUTS,      min_units=16),
        ProductOrder(GUMMY_CANDY,     min_units=12),
        ProductOrder(LIP_BALM,        min_units=8),
    ),
)

# ---------------------------------------------------------------------------
# Scenario 06 — University gym
# Athletes and students, high demand for protein and energy products.
# ---------------------------------------------------------------------------

UNIVERSITY_GYM = Scenario(
    id="S06",
    name="University gym",
    location="Gym",
    description=(
        "A vending machine beside the changing rooms of a university sports centre. "
        "Students replenish energy after workouts. Protein products and energy "
        "drinks dominate; convenience items have low uptake."
    ),
    orders=(
        ProductOrder(PROTEIN_SHAKE,   min_units=36),
        ProductOrder(PROTEIN_BAR,     min_units=30),
        ProductOrder(ENERGY_DRINK,    min_units=30),
        ProductOrder(MIXED_NUTS,      min_units=20),
        ProductOrder(SPARKLING_WATER, min_units=24),
        ProductOrder(GRANOLA_BAR,     min_units=18),
    ),
)

# ---------------------------------------------------------------------------
# Scenario 07 — Hospital waiting room
# Long waits, stressed visitors, practical needs over indulgence.
# ---------------------------------------------------------------------------

HOSPITAL_WAITING = Scenario(
    id="S07",
    name="Hospital waiting room",
    location="Hospital",
    description=(
        "A vending machine in an outpatient waiting area. Visitors and patients "
        "may wait for hours; practical, low-sugar, and medicinal items are in "
        "demand alongside staple refreshments."
    ),
    orders=(
        ProductOrder(SPARKLING_WATER,      min_units=40),
        ProductOrder(ORANGE_JUICE,         min_units=20),
        ProductOrder(COLA,                 min_units=20),
        ProductOrder(GRANOLA_BAR,          min_units=24),
        ProductOrder(CRACKERS_WITH_CHEESE, min_units=18),
        ProductOrder(PARACETAMOL,          min_units=30),
        ProductOrder(HAND_SANITIZER,       min_units=24),
        ProductOrder(FACE_MASK,            min_units=20),
    ),
)


# ===========================================================================
# Catalogue — all scenarios
# ===========================================================================

ALL_SCENARIOS: tuple[Scenario, ...] = (
    KIOSK_COLA,
    GYM_PROTEIN_BAR,
    AIRPORT_USB_CABLE,
    AIRPORT_TRANSIT,
    OFFICE_LOBBY,
    UNIVERSITY_GYM,
    HOSPITAL_WAITING,
)

SINGLE_ITEM_SCENARIOS: tuple[Scenario, ...] = tuple(
    s for s in ALL_SCENARIOS if len(s.orders) == 1
)

MULTI_ITEM_SCENARIOS: tuple[Scenario, ...] = tuple(
    s for s in ALL_SCENARIOS if len(s.orders) > 1
)

SCENARIO_BY_ID:       dict[str, Scenario] = {s.id:       s for s in ALL_SCENARIOS}
SCENARIO_BY_LOCATION: dict[str, Scenario] = {s.location: s for s in ALL_SCENARIOS}