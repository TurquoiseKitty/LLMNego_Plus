from dataclasses import dataclass

@dataclass(frozen=True)
class Product:
    """Immutable representation of a vending machine product."""
    name: str
    category: str
    market_price: float
    cost: float

    @property
    def gross_margin(self) -> float:
        return (self.market_price - self.cost) / self.market_price


# ---------------------------------------------------------------------------
# Beverages
# ---------------------------------------------------------------------------

COLA = Product(
    name="Cola (330ml)",
    category="Beverage",
    market_price=1.50,
    cost=0.30,
)

SPARKLING_WATER = Product(
    name="Sparkling water (500ml)",
    category="Beverage",
    market_price=1.20,
    cost=0.18,
)

ORANGE_JUICE = Product(
    name="Orange juice (250ml)",
    category="Beverage",
    market_price=1.80,
    cost=0.55,
)

ENERGY_DRINK = Product(
    name="Energy drink (250ml)",
    category="Beverage",
    market_price=2.50,
    cost=0.65,
)

ICED_COFFEE = Product(
    name="Iced coffee (240ml)",
    category="Beverage",
    market_price=2.80,
    cost=0.90,
)

PROTEIN_SHAKE = Product(
    name="Protein shake (330ml)",
    category="Beverage",
    market_price=3.50,
    cost=1.40,
)

# ---------------------------------------------------------------------------
# Snacks
# ---------------------------------------------------------------------------

POTATO_CHIPS = Product(
    name="Potato chips (40g)",
    category="Snack",
    market_price=1.20,
    cost=0.22,
)

CHOCOLATE_BAR = Product(
    name="Chocolate bar (50g)",
    category="Snack",
    market_price=1.50,
    cost=0.40,
)

GRANOLA_BAR = Product(
    name="Granola bar",
    category="Snack",
    market_price=1.80,
    cost=0.50,
)

MIXED_NUTS = Product(
    name="Mixed nuts (30g)",
    category="Snack",
    market_price=2.20,
    cost=0.70,
)

GUMMY_CANDY = Product(
    name="Gummy candy (50g)",
    category="Snack",
    market_price=1.00,
    cost=0.20,
)

PROTEIN_BAR = Product(
    name="Protein bar (60g)",
    category="Snack",
    market_price=3.00,
    cost=1.10,
)

CRACKERS_WITH_CHEESE = Product(
    name="Crackers with cheese (45g)",
    category="Snack",
    market_price=1.60,
    cost=0.45,
)

# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

HAND_SANITIZER = Product(
    name="Instant hand sanitizer (30ml)",
    category="Convenience",
    market_price=2.50,
    cost=0.35,
)

FACE_MASK = Product(
    name="Disposable face mask",
    category="Convenience",
    market_price=1.50,
    cost=0.18,
)

EARPHONES = Product(
    name="Earphones (basic)",
    category="Convenience",
    market_price=8.00,
    cost=1.80,
)

USB_C_CABLE = Product(
    name="Phone charging cable (USB-C)",
    category="Convenience",
    market_price=10.00,
    cost=2.20,
)

PARACETAMOL = Product(
    name="Paracetamol (16 tabs)",
    category="Convenience",
    market_price=3.50,
    cost=0.60,
)

CHEWING_GUM = Product(
    name="Chewing gum (10 pieces)",
    category="Convenience",
    market_price=0.80,
    cost=0.10,
)

LIP_BALM = Product(
    name="Lip balm",
    category="Convenience",
    market_price=2.00,
    cost=0.30,
)

# ---------------------------------------------------------------------------
# Catalogue — all products, grouped by category
# ---------------------------------------------------------------------------

ALL_PRODUCTS: tuple[Product, ...] = (
    COLA, SPARKLING_WATER, ORANGE_JUICE, ENERGY_DRINK, ICED_COFFEE, PROTEIN_SHAKE,
    POTATO_CHIPS, CHOCOLATE_BAR, GRANOLA_BAR, MIXED_NUTS, GUMMY_CANDY, PROTEIN_BAR, CRACKERS_WITH_CHEESE,
    HAND_SANITIZER, FACE_MASK, EARPHONES, USB_C_CABLE, PARACETAMOL, CHEWING_GUM, LIP_BALM,
)

BEVERAGES: tuple[Product, ...] = tuple(p for p in ALL_PRODUCTS if p.category == "Beverage")
SNACKS:    tuple[Product, ...] = tuple(p for p in ALL_PRODUCTS if p.category == "Snack")
CONVENIENCE: tuple[Product, ...] = tuple(p for p in ALL_PRODUCTS if p.category == "Convenience")

# Name-keyed lookup
PRODUCT_BY_NAME: dict[str, Product] = {p.name: p for p in ALL_PRODUCTS}