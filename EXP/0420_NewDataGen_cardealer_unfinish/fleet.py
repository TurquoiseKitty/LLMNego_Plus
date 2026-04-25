"""
fleet.py — The fixed set of 5 used cars used across all 12 experiments.

Each car exposes only two numeric properties:
    market_price_new : new-car MSRP reference M,  PUBLIC  (buyer sees this)
    dealer_cost      : the dealer's acquisition cost, PRIVATE to the seller

The five cars are chosen so that the cost-to-M ratio spans roughly 20 % -> 80 %
in roughly equal steps.  This gives the 12 experiments a wide spectrum of
economic scenarios:

    * Low ratios (20-35 %)  => the dealer has a large margin to give back; the
      floor is far below M and the bargaining zone is wide.  Good data for
      seeing how strategies behave when the seller has plenty of room to move.

    * Middle ratio (~50 %) => the classical textbook case where the walk-away
      price sits roughly in the middle of the public reference.

    * High ratios (65-80 %) => the dealer's floor is close to M; almost every
      buyer bid will be below the floor, so strategies are stress-tested on
      how they hold firm near the end of the bargaining zone.

Target vs. actual ratios (dealer_cost / market_price_new):
    Mercedes S550  :  19000 /  96000 ~= 0.198  (target 0.20)
    Cadillac CTS   :  15750 /  45000  = 0.350  (target 0.35)
    Honda Accord   :  14000 /  28000  = 0.500  (target 0.50)
    Toyota RAV4    :  20800 /  32000  = 0.650  (target 0.65)
    Ford Mustang GT:  36000 /  45000  = 0.800  (target 0.80)
"""

from __future__ import annotations

from seller_prompt_ensemble import VehicleSpec


FLEET: list[VehicleSpec] = [
    # ---------------- ~20 % : aged luxury, heavy depreciation ----------------
    VehicleSpec(
        car_name="2014 Mercedes-Benz S550",
        public_description=(
            "full-size luxury sedan, 112,800 miles, 4.7L twin-turbo V8, "
            "original MSRP around the mid-$90k range, panoramic roof, "
            "ventilated and massaging seats, recent major service, tires "
            "replaced within the last year, some minor wear on the driver's "
            "seat bolster, two prior owners, clean title"
        ),
        market_price_new="96000",
        dealer_cost="19000",
    ),

    # ---------------- ~35 % : older luxury sport sedan -----------------------
    VehicleSpec(
        car_name="2016 Cadillac CTS 3.6 Luxury",
        public_description=(
            "midsize luxury sport sedan, 84,500 miles, 3.6L V6 RWD, Bose "
            "audio, navigation, heated leather seats, CUE infotainment, "
            "very good cosmetic condition, routine service up to date, "
            "two prior owners, clean CarFax, original MSRP mid-$40k"
        ),
        market_price_new="45000",
        dealer_cost="15750",
    ),

    # ---------------- ~50 % : mid-life compact family car --------------------
    VehicleSpec(
        car_name="2019 Honda Accord Sport 1.5T",
        public_description=(
            "midsize sedan, 62,100 miles, 1.5L turbo, CVT, one prior owner, "
            "complete dealer service history, Apple CarPlay / Android Auto, "
            "Honda Sensing safety suite, dual-zone climate, excellent overall "
            "condition, original MSRP around the high-$20k range"
        ),
        market_price_new="28000",
        dealer_cost="14000",
    ),

    # ---------------- ~65 % : lightly used newer SUV -------------------------
    VehicleSpec(
        car_name="2022 Toyota RAV4 XLE AWD",
        public_description=(
            "compact SUV, 28,400 miles, 2.5L I4 AWD, one owner, still under "
            "powertrain warranty, Toyota Safety Sense 2.0, blind-spot monitor, "
            "power liftgate, all service records on hand, tires near new, "
            "clean CarFax, original MSRP around $32k"
        ),
        market_price_new="32000",
        dealer_cost="20800",
    ),

    # ---------------- ~80 % : nearly new performance car ---------------------
    VehicleSpec(
        car_name="2023 Ford Mustang GT Premium",
        public_description=(
            "two-door sports coupe, 9,200 miles, 5.0L V8, 10-speed automatic, "
            "Premium package with 12-inch digital cluster and active exhaust, "
            "one owner, original MSRP around the mid-$40k range, garage-kept, "
            "spotless cosmetic and mechanical condition, full balance of the "
            "factory bumper-to-bumper warranty remaining"
        ),
        market_price_new="45000",
        dealer_cost="36000",
    ),
]


def fleet_as_records() -> list[dict]:
    """Small dict view for inclusion in experiment metadata / manifests."""
    return [
        {
            "car_name": c.car_name,
            "public_description": c.public_description,
            "market_price_new": float(c.market_price_new),
            "dealer_cost": float(c.dealer_cost),
            "cost_over_market_ratio": round(
                float(c.dealer_cost) / float(c.market_price_new), 4
            ),
        }
        for c in FLEET
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(fleet_as_records(), indent=2))
