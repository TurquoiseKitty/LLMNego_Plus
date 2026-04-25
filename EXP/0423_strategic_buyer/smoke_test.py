"""
smoke_test.py -- Pre-flight checks for the 0423 LLM-buyer sweep.

Two levels:
    --api=0 (default)  : no API calls; just exercises imports, prompt
                         building for both sides, parsing, and the 12-exp
                         manifest. Runs in well under a second.
    --api=1            : also make 1 round-trip to the DeepSeek endpoint
                         with the smallest possible request so credentials
                         and connectivity are confirmed.
    --negotiate        : run one full 3-round negotiation (6 LLM calls,
                         ~1-2 min) end-to-end against the real API.
"""

from __future__ import annotations

import argparse
import sys

import config
from fleet import FLEET
from experiments import EXPERIMENTS
from seller_prompt_ensemble import build_prompt, STRATEGIES
from buyer_prompt_ensemble import build_buyer_prompt, BUYER_STRATEGIES
from negotiation import extract_price


def check_imports_and_prompts() -> None:
    print("[1/3] imports + prompt builders")
    # seller side
    assert set(STRATEGIES) == {
        "patient_value_defender", "busy_impatient_closer",
        "friendly_rapport_builder", "reciprocal_fairness_keeper",
        "opponent_aware_diagnostic", "market_expert_value_justifier",
    }, f"unexpected seller strategy set: {set(STRATEGIES)}"
    # buyer side
    assert "natural_buyer" in BUYER_STRATEGIES
    for k in STRATEGIES:
        assert k in BUYER_STRATEGIES, f"mirror buyer missing for seller key {k!r}"

    # build one prompt on each side for each car
    for car in FLEET:
        for k in STRATEGIES:
            p = build_prompt(k, FLEET, car.car_name)
            assert "[PRICE]" in p and car.car_name in p
            assert f"${int(float(car.dealer_cost))}" in p, \
                f"dealer cost missing from seller prompt for {car.car_name}"
        for k in BUYER_STRATEGIES:
            bp = build_buyer_prompt(k, FLEET, car.car_name)
            assert "[PRICE]" in bp and car.car_name in bp
            # The buyer must never see the dealer cost.
            dc = str(int(float(car.dealer_cost)))
            assert f"acquisition cost for this vehicle is ${dc}" not in bp, \
                f"LEAK: buyer prompt contains dealer cost for {car.car_name} / {k}"
    print("      OK")


def check_experiment_manifest() -> None:
    print("[2/3] 12-experiment manifest")
    assert len(EXPERIMENTS) == 12
    for i, exp in enumerate(EXPERIMENTS):
        assert exp["index"] == i
        assert "seller_schedule" in exp and "buyer_schedule" in exp
        assert exp["seller_schedule"].schedule
        assert exp["buyer_schedule"].schedule
    groups = [e["group"] for e in EXPERIMENTS]
    assert groups[:6] == ["natural_buyer"] * 6
    assert groups[6:] == ["mirror_buyer"] * 6
    # Mirror experiments: buyer strategy == seller strategy
    for e in EXPERIMENTS[6:]:
        assert e["buyer_strategy"] == e["seller_strategy"], \
            f"mirror pairing broken for exp {e['index']}: " \
            f"seller={e['seller_strategy']} buyer={e['buyer_strategy']}"
    for e in EXPERIMENTS:
        print(f"  {e['index']:>2}  {e['tag']}")
    print("      OK")


def check_price_parser() -> None:
    print("[3/3] [PRICE] parser")
    car = "2019 Honda Accord Sport 1.5T"
    samples = [
        ("I'll offer you this.\n\n[PRICE] 2019 Honda Accord Sport 1.5T: $14,250.00", 14250.0),
        ("ok\n[PRICE] 2019 Honda Accord Sport 1.5T: $9999.99", 9999.99),
        ("[PRICE] 2019 Honda Accord Sport 1.5T: $0.50", 0.50),
    ]
    for s, want in samples:
        got = extract_price(s, car)
        assert got == want, f"parser fail: got={got}, want={want}, text={s!r}"
    # Bad input returns None
    assert extract_price("no price here at all", car) is None
    print("      OK")


def api_roundtrip() -> None:
    print("[API] one minimal round-trip to DeepSeek")
    from openai import OpenAI
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "Reply with the single word: OK."},
            {"role": "user",   "content": "ping"},
        ],
        max_tokens=64,
        extra_body=dict(config.THINKING_EXTRA_BODY),
    )
    print("      model replied:", (resp.choices[0].message.content or "").strip()[:120])


def full_negotiation(n_rounds: int = 3) -> None:
    print(f"[NEG] running one {n_rounds}-round negotiation end-to-end")
    from openai import OpenAI
    from negotiation import run_single_negotiation
    from seller_schedule import fixed_schedule
    from buyer_schedule import fixed_buyer_schedule
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    result = run_single_negotiation(
        client=client,
        model=config.DEEPSEEK_MODEL,
        active_car=FLEET[2],  # the mid-ratio Honda Accord
        fleet=FLEET,
        seller_schedule=fixed_schedule("patient_value_defender", n_rounds),
        buyer_schedule=fixed_buyer_schedule("natural_buyer", n_rounds),
        n_rounds=n_rounds,
        rng_seed=20260423,
        verbose=True,
    )
    ok = all(r["buyer_price"] is not None and r["seller_price"] is not None
             for r in result["rounds"])
    print("      full-negotiation OK" if ok else "      full-negotiation had parse failures")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", type=int, default=0, help="1 = also do a minimal API ping")
    ap.add_argument("--negotiate", action="store_true",
                    help="Run one short full negotiation end-to-end.")
    args = ap.parse_args()

    check_imports_and_prompts()
    check_experiment_manifest()
    check_price_parser()
    if args.api:
        api_roundtrip()
    if args.negotiate:
        full_negotiation(n_rounds=3)
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
