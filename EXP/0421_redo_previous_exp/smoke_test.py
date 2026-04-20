"""
smoke_test.py -- Minimal pre-flight check before launching the 12-hour sweep.

What it does (in the default 1-call mode):
    * Builds the exact DeepSeek client that worker.py uses (config.py values).
    * Invokes negotiation.call_seller_llm() once, with the Mercedes S550
      (~20 % ratio car) as the active vehicle and a single canned buyer
      opening bid.  Uses the `patient_value_defender` strategy.
    * Verifies:
        - the call does not raise,
        - msg.reasoning_content is non-empty  (DeepSeek reasoner signature),
        - msg.content ends with a parseable [PRICE] line,
        - the parsed seller price is a positive float.
    * Prints a structured report and exits 0 on success, non-zero on failure.

Runtime: one deepseek-reasoner call, typically ~15-25 s and a few cents.

Usage:
    python smoke_test.py           # 1 call, ~20 s, minimal cost
    python smoke_test.py --full    # 16-round negotiation (~5 min, ~$0.05)
"""

from __future__ import annotations

import argparse
import sys
import time

import config
from fleet import FLEET
from negotiation import (
    call_seller_llm,
    extract_seller_price,
    make_buyer_message,
    run_single_negotiation,
)
from seller_prompt_ensemble import build_prompt
from seller_schedule import fixed_schedule
from worker import _build_client


def _check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail else ""), flush=True)
    return condition


def smoke_one_call() -> int:
    print("=== DeepSeek one-call smoke test ===", flush=True)
    print(f"  {config.summarise()}", flush=True)

    car = FLEET[0]
    strategy = "patient_value_defender"

    # Minimal buyer history: one opening bid.
    import random
    rng = random.Random(0)
    buyer_msg, _ = make_buyer_message(car.car_name, 12345.00, rng)
    history = [{"speaker": "BUYER", "content": buyer_msg}]

    # Build the exact system prompt the worker would send.
    system_prompt = build_prompt(
        strategy_key=strategy,
        fleet=FLEET,
        active_car_name=car.car_name,
    )

    client = _build_client(config.DEEPSEEK_API_KEY, config.DEEPSEEK_BASE_URL)

    t0 = time.time()
    try:
        answer, reasoning = call_seller_llm(
            client=client,
            model=config.DEEPSEEK_MODEL,
            system_prompt=system_prompt,
            history=history,
            opening=True,
        )
    except Exception as e:
        print(f"  [FAIL] API call raised: {type(e).__name__}: {e}", flush=True)
        return 2
    dt = time.time() - t0

    price = extract_seller_price(answer, car.car_name)

    print("", flush=True)
    print("--- response ---", flush=True)
    print(f"  latency       : {dt:.1f} s", flush=True)
    print(f"  answer length : {len(answer)} chars", flush=True)
    print(f"  reasoning len : {len(reasoning) if reasoning else 0} chars", flush=True)
    print(f"  parsed price  : {price}", flush=True)
    print("", flush=True)
    print("--- answer head (first 400 chars) ---", flush=True)
    print(answer[:400], flush=True)
    print("", flush=True)
    print("--- reasoning head (first 300 chars) ---", flush=True)
    print((reasoning or "<NONE>")[:300], flush=True)
    print("", flush=True)

    print("--- checks ---", flush=True)
    ok = True
    ok &= _check("call returned",          answer is not None and len(answer) > 0)
    ok &= _check("answer contains [PRICE]", "[PRICE]" in answer,
                 "seller follows the required response format")
    ok &= _check("price parseable",         isinstance(price, float) and price > 0,
                 f"parsed ${price}" if price else "no dollar amount")
    ok &= _check("reasoning_content present",
                 reasoning is not None and len(reasoning) > 0,
                 "DeepSeek reasoner returned a chain-of-thought")
    ok &= _check("reasoning != content",
                 reasoning != answer,
                 "reasoning and final answer are distinct fields")

    print("", flush=True)
    if ok:
        print("=== SMOKE TEST PASSED ===", flush=True)
        print("  -> ready to run the full sweep with:  python launcher.py", flush=True)
        return 0
    print("=== SMOKE TEST FAILED ===", flush=True)
    return 1


def smoke_full_negotiation() -> int:
    """Run one complete 16-round negotiation on Transition B (exp 9, car 0).

    This is the most thorough single-negotiation check: it exercises both
    switch points (r=6 and r=12) and all three strategies in Transition B.
    """
    print("=== DeepSeek full-negotiation smoke test (Transition B, Mercedes) ===",
          flush=True)
    print(f"  {config.summarise()}", flush=True)

    from experiments import EXPERIMENTS
    exp = EXPERIMENTS[9]          # transitionB rep1
    schedule = exp["seller_schedule"]
    car = FLEET[0]                # Mercedes S550 (~20 % ratio)

    client = _build_client(config.DEEPSEEK_API_KEY, config.DEEPSEEK_BASE_URL)

    t0 = time.time()
    try:
        run = run_single_negotiation(
            client=client,
            model=config.DEEPSEEK_MODEL,
            active_car=car,
            fleet=FLEET,
            seller_schedule=schedule,
            n_rounds=config.N_ROUNDS,
            rng_seed=42,
            verbose=True,
        )
    except Exception as e:
        print(f"\n[FAIL] negotiation raised: {type(e).__name__}: {e}", flush=True)
        return 2
    dt = time.time() - t0

    rounds = run["rounds"]
    n_reasoning = sum(1 for r in rounds if r["seller_reasoning"])
    n_parsed    = sum(1 for r in rounds if r["seller_price"] is not None)

    print("", flush=True)
    print("--- summary ---", flush=True)
    print(f"  total time       : {dt/60:.1f} min  ({dt/len(rounds):.1f} s/round)", flush=True)
    print(f"  rounds run       : {len(rounds)}  / {config.N_ROUNDS} expected", flush=True)
    print(f"  rounds w/reason  : {n_reasoning}", flush=True)
    print(f"  rounds w/price   : {n_parsed}", flush=True)
    print(f"  strategies seen  : {sorted(set(r['seller_active_strategy'] for r in rounds))}",
          flush=True)

    print("", flush=True)
    print("--- checks ---", flush=True)
    ok = True
    ok &= _check("ran all rounds",          len(rounds) == config.N_ROUNDS)
    ok &= _check("reasoning on every round", n_reasoning == len(rounds))
    ok &= _check("prices parsed on every round", n_parsed == len(rounds))
    ok &= _check("all three strategies appeared",
                 len(set(r["seller_active_strategy"] for r in rounds)) == 3)

    print("", flush=True)
    if ok:
        print("=== FULL SMOKE TEST PASSED ===", flush=True)
        return 0
    print("=== FULL SMOKE TEST FAILED ===", flush=True)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="Run one full 16-round negotiation (~5 min) instead "
                         "of a single API call (~20 s).")
    args = ap.parse_args()

    if args.full:
        return smoke_full_negotiation()
    return smoke_one_call()


if __name__ == "__main__":
    sys.exit(main())
