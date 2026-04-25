"""
smoke_test.py -- Pre-flight check.

Two modes:

  --mode api        One real API call to verify credentials + network.
                    ~10-20 s, costs a few cents.

  --mode mock       Run one full 20-round negotiation using a LOCAL mock
                    seller (no API call).  Validates the end-to-end pipeline:
                    buyer scheme -> message template -> history format ->
                    seller-price regex -> JSON schema.  ~2 s, $0.

  --mode full       One real 20-round negotiation against deepseek-reasoner.
                    ~3-6 min, a few cents.  Checks the live pipeline.

Default: mock.  Run mock before api to catch dumb bugs without spending money.

Usage:
    python smoke_test.py
    python smoke_test.py --mode api
    python smoke_test.py --mode full
    python smoke_test.py --mode full --scheme E --policy chatterjee_fair_midpoint
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import config
from fleet import FLEET
from buyer_schemes import get_scheme
from negotiation import run_single_negotiation, extract_seller_price


# ----------------------------------------------------------------------
# Mock seller (no network)
# ----------------------------------------------------------------------

class _MockSellerClient:
    """Stand-in for openai.OpenAI that returns a sane seller reply.

    Behaviour: greedy-ish dealer with linear-ish concession.  The emitted
    message always contains a valid [PRICE] line so extract_seller_price
    succeeds.
    """
    class _Choices:
        def __init__(self, message): self.message = message
    class _Message:
        def __init__(self, content, reasoning=None):
            self.content = content
            self.reasoning_content = reasoning
    class _Resp:
        def __init__(self, content, reasoning=None):
            self.choices = [_MockSellerClient._Choices(_MockSellerClient._Message(content, reasoning))]
    class _Chat:
        def __init__(self, outer): self.completions = outer
    def __init__(self): self.chat = _MockSellerClient._Chat(self); self._t = 0
    def create(self, *, model, messages, **kwargs):  # noqa: ANN001
        self._t += 1
        # Dumb policy: $90,000 initial, concede $5,000/round, floor $30,000.
        price = max(30000.0, 90000.0 - 5000.0 * (self._t - 1))
        # Pull car name from system prompt if possible
        system = messages[0]["content"]
        car_name = "the vehicle"
        for line in system.splitlines():
            if line.startswith("Car:"):
                car_name = line.split(":", 1)[1].strip()
                break
        body = f"Thanks for your offer. I can offer this car for ${price:,.2f}.\n\n[PRICE] {car_name}: ${price:.2f}"
        return _MockSellerClient._Resp(body, reasoning="mock reasoning")


def _smoke_mock(scheme_key: str, policy_key: str) -> int:
    print(f"[smoke-mock] scheme={scheme_key}  policy={policy_key}")
    vehicle = FLEET[0]
    scheme = get_scheme(scheme_key)
    client = _MockSellerClient()
    run = run_single_negotiation(
        client=client,
        model="mock-seller",
        active_car=vehicle,
        fleet=FLEET,
        policy_key=policy_key,
        buyer_scheme=scheme,
        n_rounds=config.N_ROUNDS,
        rng_seed=42,
        verbose=True,
    )
    rounds = run["rounds"]
    parse_fails = sum(1 for r in rounds if r["seller_price"] is None)
    print(f"\n[smoke-mock] n_rounds_generated={len(rounds)}  "
          f"n_rounds_planned={run['n_rounds_planned']}  "
          f"agreed={run['agreed']}  "
          f"agreement_round={run['agreement_round']}  "
          f"parse_fails={parse_fails}")
    # With early-agreement termination we expect 1 <= generated <= N_ROUNDS
    assert 1 <= len(rounds) <= config.N_ROUNDS, \
        f"generated rounds out of range: got {len(rounds)}, expected 1..{config.N_ROUNDS}"
    # If the run reported agreement, the agreement turn must match the last round
    if run["agreed"]:
        assert run["agreement_round"] == len(rounds), \
            f"agreed=True but agreement_round ({run['agreement_round']}) != last round ({len(rounds)})"
        assert rounds[-1]["is_agreement"], "last round should carry is_agreement=True"
    # If the run did NOT report agreement, it ran to the full T
    else:
        assert len(rounds) == config.N_ROUNDS, \
            f"no agreement but only {len(rounds)} rounds generated"
    assert parse_fails == 0, f"mock seller parse failed on {parse_fails} rounds"
    print("[smoke-mock] OK")
    return 0


def _smoke_api() -> int:
    print("[smoke-api] one deepseek-reasoner ping ...")
    from openai import OpenAI
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "Respond with exactly one word."},
            {"role": "user",   "content": "ping"},
        ],
        max_tokens=256,
        extra_body=dict(config.THINKING_EXTRA_BODY),
    )
    msg = resp.choices[0].message
    print(f"[smoke-api] content: {msg.content!r}")
    print(f"[smoke-api] reasoning present: {hasattr(msg, 'reasoning_content') and bool(getattr(msg, 'reasoning_content', None))}")
    print("[smoke-api] OK")
    return 0


def _smoke_full(scheme_key: str, policy_key: str) -> int:
    print(f"[smoke-full] scheme={scheme_key}  policy={policy_key}")
    from openai import OpenAI
    vehicle = FLEET[0]
    scheme = get_scheme(scheme_key)
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    run = run_single_negotiation(
        client=client,
        model=config.DEEPSEEK_MODEL,
        active_car=vehicle,
        fleet=FLEET,
        policy_key=policy_key,
        buyer_scheme=scheme,
        n_rounds=config.N_ROUNDS,
        rng_seed=42,
        verbose=True,
    )
    rounds = run["rounds"]
    parse_fails = sum(1 for r in rounds if r["seller_price"] is None)
    print(f"\n[smoke-full] n_rounds_generated={len(rounds)}  "
          f"n_rounds_planned={run['n_rounds_planned']}  "
          f"agreed={run['agreed']}  "
          f"agreement_round={run['agreement_round']}  "
          f"parse_fails={parse_fails}")
    if parse_fails > 0:
        print(f"  !! {parse_fails} parse failures; inspect rounds:", file=sys.stderr)
        for r in rounds:
            if r["seller_price"] is None:
                print(f"     round {r['round']}: {r['seller_answer'][:200]!r}", file=sys.stderr)
    return 0 if parse_fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode",   type=str, default="mock", choices=["mock", "api", "full"])
    ap.add_argument("--scheme", type=str, default="E", choices=["E"])
    ap.add_argument("--policy", type=str, default="fu_high_price_brief_anchor")
    args = ap.parse_args()
    if args.mode == "mock":
        return _smoke_mock(args.scheme, args.policy)
    if args.mode == "api":
        return _smoke_api()
    return _smoke_full(args.scheme, args.policy)


if __name__ == "__main__":
    sys.exit(main())
