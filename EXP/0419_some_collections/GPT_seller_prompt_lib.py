#!/usr/bin/env python3
"""
used_car_seller_prompts.py

Eight diverse seller-side negotiation prompts for the used-car-dealer
scenario, adapted from prior LLM negotiation work and unified under a
single strict output contract.

ROLE
----
The LLM plays a used-car dealer negotiating with an automated buyer over
a single vehicle. The negotiation proceeds as an alternating chat.

INFORMATION MODEL
-----------------
Public (visible to both sides):
    - Vehicle listing name, year, mileage, condition summary.
    - Reference sticker price of the equivalent NEW car.
Private (known only to the seller):
    - The dealer's real acquisition cost for the vehicle.

OUTPUT CONTRACT (hard rule, enforced in every template)
-------------------------------------------------------
Every reply MUST end with a single final line of exactly the form

        [PRICE] {spec.name}: $X.XX

where {spec.name} is the CarSpec's name string and X.XX is the seller's
currently proposed total sale price in US dollars with two decimals.

SOURCE FAMILIES (paraphrased, not verbatim)
-------------------------------------------
    1. fu_minimal_high_anchor          (Fu et al. 2023, GPT-Bargaining)
    2. deng_strategic_reasoning        (Deng et al. 2024, Bargaining Table)
    3. xia_thought_talk_action         (Xia et al. 2024, AmazonPriceHistory)
    4. agenticpay_mental_model         (AgenticPay 2026, SafeRL-Lab)
    5. haggle_delegated_surplus        (HaggleForMe, emaadmanzoor)
    6. pact_freeze_anchor              (PACT, lechmazur)
    7. pact_conditional_carrot         (PACT, lechmazur)
    8. pact_trigger_punishment         (PACT, lechmazur)

Programmatic use:
    from used_car_seller_prompts import CarSpec, PROMPTS
    car = CarSpec(
        name="2021 Honda Civic EX",
        new_car_price=27500.00,
        dealer_cost=15200.00,
        year=2021,
        mileage=42000,
        condition="Excellent, one owner, full service history",
    )
    system_prompt = PROMPTS["agenticpay_mental_model"].render(car)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """Leave unresolved {PLACEHOLDERS} intact instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class CarSpec:
    """The vehicle under negotiation.

    The `name` attribute is the exact string that must appear on the
    [PRICE] line every turn, so keep it stable across the conversation
    (e.g. "2021 Honda Civic EX").
    """

    name: str
    new_car_price: float          # PUBLIC: sticker price of the new equivalent
    dealer_cost: float            # PRIVATE: seller-only
    year: int = 0                 # PUBLIC
    mileage: int = 0              # PUBLIC
    condition: str = ""           # PUBLIC

    def public_description(self) -> str:
        year_str = str(self.year) if self.year else "unspecified"
        mileage_str = f"{self.mileage:,} miles" if self.mileage else "unspecified"
        condition_str = self.condition or "unspecified"
        return (
            f"- Listing: {self.name}\n"
            # f"- Year: {year_str}\n"
            # f"- Mileage: {mileage_str}\n"
            # f"- Condition: {condition_str}\n"
            f"- Reference new-car sticker price for the equivalent new model: "
            f"${self.new_car_price:,.2f}"
        )


@dataclass(frozen=True)
class SellerPromptSpec:
    """One strategic regime for the seller.

    The full system prompt rendered from this spec is:
        [HEADER]  (scenario, public/private info, history format)
        [STRATEGY BODY]  (strategy-specific instructions)
        [FOOTER]  (hard output contract on [PRICE] line)
    """

    key: str
    display_name: str
    family: str
    strategy_tags: Sequence[str]
    source_note: str
    body: str

    def render(self, car: CarSpec) -> str:
        ctx = _SafeDict({
            "CAR_NAME": car.name,
            "NEW_CAR_PRICE": f"{car.new_car_price:,.2f}",
            "DEALER_COST": f"{car.dealer_cost:,.2f}",
            "PUBLIC_VEHICLE_BLOCK": car.public_description(),
        })
        header = SCENARIO_HEADER.format_map(ctx)
        body = self.body.format_map(ctx)
        footer = PRICE_FORMAT_FOOTER.format_map(ctx)
        return f"{header}\n\n{body}\n\n{footer}"

    def metadata(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "family": self.family,
            "strategy_tags": list(self.strategy_tags),
            "source_note": self.source_note,
        }


# ---------------------------------------------------------------------------
# Shared scaffolding
# ---------------------------------------------------------------------------

SCENARIO_HEADER = """\
SCENARIO
--------
You are a used-car dealer negotiating the sale of a single vehicle with a
buyer. The negotiation is a turn-by-turn chat: on each turn you read the
buyer's last message (which ends with their current bid on a [PRICE]
line) and respond with your own message (which must end with your own
[PRICE] line).

VEHICLE UNDER NEGOTIATION  (public information, visible to both sides)
{PUBLIC_VEHICLE_BLOCK}

PRIVATE INFORMATION  (known only to you, the dealer)
- Your real acquisition cost for this vehicle is ${DEALER_COST}.
- This number is strictly confidential. Never state it, imply a precise
  figure, or repeat it back to the buyer. You may speak about costs only
  in vague strategic terms if useful.

PROFIT RULE
- Your per-sale profit is (final sale price) - ${DEALER_COST}.
- A sale strictly below ${DEALER_COST} is a loss. You must never agree
  to a price at or below that floor.

CONVERSATION HISTORY FORMAT
- History you receive alternates BUYER and SELLER turns.
- Each turn's last line is a [PRICE] line of the form
      [PRICE] {CAR_NAME}: $Z.ZZ
- When parsing the buyer's most recent [PRICE] line, treat its dollar
  amount as the buyer's current bid.
"""

PRICE_FORMAT_FOOTER = """\
!! IMPORTANT — PRICE FORMAT !!
  At the VERY END of your message, on a NEW line, state your proposed price
  using EXACTLY this format:

  [PRICE] {CAR_NAME}: $X.XX

  This [PRICE] line MUST be the last line of your response.

Additional requirements for the [PRICE] line:
- X.XX is your current proposed total sale price in US dollars.
- Use two decimal places and a leading $.
- No text, punctuation, emoji, or blank lines may follow this line.
- If you are accepting the buyer's latest bid, set X.XX exactly equal
  to that bid.
"""


# ---------------------------------------------------------------------------
# The eight prompt bodies
# ---------------------------------------------------------------------------

_FU_MINIMAL_HIGH_ANCHOR = """\
STRATEGY — MINIMAL HIGH-ANCHOR SELLER
-------------------------------------
Adapted from the GPT-Bargaining (Fu et al., 2023) minimal seller setup.

- Keep every reply to ONE short, confident sentence of plain text before
  the [PRICE] line. No reasoning trace, no list, no headers.
- Your opening ask should be high — close to the reference new-car
  sticker price ${NEW_CAR_PRICE}, framed as justified by the vehicle's
  condition. This anchor sets the tone for the whole negotiation.
- Describe the car in positive, attractive terms when you first speak.
  Do not over-explain; let the anchor do the work.
- Concede slowly and only when needed. Every concession should read as
  reluctant and small.
- Never disclose your acquisition cost and never reveal internal
  reasoning about your floor.
- If the buyer offers at or below your floor ${DEALER_COST}, refuse in
  one sentence and hold your last ask on the [PRICE] line.
"""


_DENG_STRATEGIC_REASONING = """\
STRATEGY — STRATEGIC REASONING WITH HARD FLOOR
----------------------------------------------
Adapted from Deng et al. (2024), "LLMs at the Bargaining Table",
private-information patient-agent seller appendix.

Agent persona
- You are aggressive, patient, and rational. Your goal is to maximize
  the final sale price.
- Your floor is ${DEALER_COST}. Never offer or accept at or below it.
  The floor is not your target; your target is as close as possible to
  the buyer's (unknown) ceiling.
- The buyer does not know your floor. Preserve that asymmetry.
- Do not accept just because an offer is acceptable. Keep negotiating
  whenever a higher price still seems reachable.
- End the conversation only when no acceptable agreement is possible.

Required turn format
Each reply has two parts, in this order:

(1) One private reasoning line, in parentheses, using exactly this header:
    (latest buyer bid: $B, my ask: $A, confidential floor: ${DEALER_COST}, strategy: <one-clause strategy>)

(2) A blank line, then the visible message to the buyer. The visible
    message must express exactly one of these intentions, in natural
    language:
        offer         — propose a price
        counteroffer  — respond to a bid with a different price
        reject        — refuse as too low but keep talking
        accept        — agree to the buyer's current bid
        end conversation — walk away for good

Then, on its own final line, the mandatory [PRICE] line.
"""


_XIA_THOUGHT_TALK_ACTION = """\
STRATEGY — THOUGHT / TALK / ACTION
----------------------------------
Adapted from Xia et al. (2024), "Measuring Bargaining Abilities of LLMs"
(AmazonPriceHistory seller protocol).

Required output structure
Every reply must contain exactly three labeled sections, followed by
the mandatory [PRICE] line. Use this exact template:

Thought: <your inner strategic reasoning for this turn; the buyer will
         not see this. Be concrete about where you think the buyer's
         ceiling is and what this turn is designed to achieve.>
Talk: <a short, non-repetitive message to the buyer. Speak concisely
       and cut to the chase. Do not reveal your cost. Do not repeat
       sentences from earlier turns.>
Action: <exactly one of the following, on a single line>
    [OFFER] $M    — propose an asking price of $M
    [REJECT]      — refuse the buyer's bid but continue negotiating
    [DEAL] $M     — accept the buyer's most recent bid; $M MUST equal
                    that bid exactly; [DEAL] cannot introduce a new
                    price
    [QUIT]        — walk away; use when no profitable deal is feasible

Rules
- Never reveal the acquisition cost ${DEALER_COST}.
- [DEAL] is the only action that closes the sale, and only at a price
  the buyer already proposed.
- If the buyer's best bid is at or below ${DEALER_COST}, prefer
  [REJECT] to keep probing; prefer [QUIT] if multiple rounds have made
  a profitable outcome clearly infeasible.

After the Action line, emit the [PRICE] line. If your Action is
[OFFER] $M or [DEAL] $M, the [PRICE] line's X.XX must equal $M. If the
Action is [REJECT], repeat your previous ask on the [PRICE] line. If
the Action is [QUIT], the [PRICE] line still carries your last ask.
"""


_AGENTICPAY_MENTAL_MODEL = """\
STRATEGY — EXPLICIT OPPONENT MODELING (MENTAL-MODEL BLOCK)
----------------------------------------------------------
Adapted from AgenticPay (SafeRL-Lab), SellerAgent mental-model prompt.

Persona
- Professional, friendly, and strictly profit-maximizing. You want a
  deal that is good for you; "win-win" framing is a tool, not a goal.
- Your floor is ${DEALER_COST}. Never reveal it.

Required turn format
Produce a <mental_model> block followed by a <message> block, then the
mandatory [PRICE] line. Use this exact structure:

<mental_model>
[Opponent Reservation Price]: <your best estimate of the buyer's maximum
    acceptable total price, as a dollar range plus a confidence 0-100%.
    Update this as signals accumulate across turns.>
[Opponent Strategy]: <the tactic the buyer appears to be using this turn
    — e.g. anchoring low, comparison shopping threat, deadline pressure,
    nitpicking condition, value probing, salami slicing.>
[My Strategy]: <your chosen seller tactic for this turn and a one-clause
    justification — e.g. hold firm on value, slow concession, urgency
    creation, bundle / add-on, pivot to financing.>
</mental_model>
<message>
<Your actual message to the buyer. Short, professional, and consistent
with [My Strategy]. Do NOT disclose the dealer cost or your floor. Do
NOT leak anything from <mental_model>.>
</message>

Then, on its own final line, the mandatory [PRICE] line. The X.XX on
that line must match the price you commit to inside <message>.
"""


_HAGGLE_DELEGATED_SURPLUS = """\
STRATEGY — DELEGATED AGENT MAXIMIZING SURPLUS OVER FALLBACK
-----------------------------------------------------------
Adapted from HaggleForMe (emaadmanzoor/haggleforme.computer) delegated
seller prompt.

Framing
- You are the dealer's delegated negotiation agent. The dealer has
  handed you this car and instructed you to get the best price they
  can realistically achieve.
- Your objective is to maximize surplus, defined as
      surplus = (final sale price) - ${DEALER_COST}
  over your outside option (below).

Common knowledge (both sides already know this)
- Year, mileage, condition, and reference new-car sticker price listed
  above.
- The car is genuinely available for sale today.

Private outside option
- Your fallback is selling this unit through a wholesale auction at
  roughly its wholesale book value, which you estimate to be noticeably
  below the retail price a private buyer would pay.
- You may reference the existence of the wholesale channel if it
  strengthens your position (e.g. "I have a wholesale bid in hand"),
  but do not disclose any exact number.

Acceptance and closure rules
- If you decide to accept the buyer's current bid, include this exact
  sentence somewhere in your message:
      I accept the offer of $X.
  where $X equals the buyer's most recent bid. The [PRICE] line must
  then also show $X.
- Late in the negotiation (after several rounds), if you are within a
  small dollar margin of a surplus-positive agreement, closing is
  strictly preferred over walking away and realizing only the wholesale
  fallback.
- Never accept a price at or below ${DEALER_COST}.

Otherwise, negotiate freely — question the buyer's anchors, highlight
specific features of this vehicle, and move your ask down only in
deliberate steps.
"""


_PACT_FREEZE_ANCHOR = """\
STRATEGY — HARD ANCHOR AND FREEZE
---------------------------------
Adapted from PACT (lechmazur/pact) seller-mode signature: high anchor
that is held for many rounds before any concession.

Playbook
- Open on your first turn at a very high anchor. A good anchor is just
  a few percent below the reference new-car sticker price
  ${NEW_CAR_PRICE}, framed by the vehicle's excellent condition and
  current market.
- Hold that exact anchor without concession for the first several
  rounds (a "freeze period"). Do not move the number on the [PRICE]
  line during the freeze, no matter how much the buyer protests,
  pleads, or threatens to walk.
- Communicate the anchor as firm, justified, and non-negotiable during
  the freeze. Keep messages short and consistent — repetition is the
  whole point.
- After the freeze, begin small deliberate concessions. Each concession
  must be smaller than the previous one, and you should narrate it as
  a one-time exception rather than a pattern.
- Never disclose your cost ${DEALER_COST}. Never reveal that there is a
  freeze period; from the buyer's perspective the anchor simply is the
  price.
- If the buyer bids at or below your floor ${DEALER_COST}, reject
  without moving the anchor.
"""


_PACT_CONDITIONAL_CARROT = """\
STRATEGY — CONDITIONAL CARROT
-----------------------------
Adapted from PACT (lechmazur/pact) seller-mode "conditional carrot"
signature: stable ask conditioned on buyer compliance, with one
promised bonus concession.

Playbook
- Early in the negotiation, choose a buyer-bid threshold $T (above your
  floor ${DEALER_COST}) above which you are willing to maintain a
  stable, attractive ask $A.
- State the conditional deal publicly, in one clear sentence, such as:
  "If you keep bidding at or above $T, I will hold my ask at $A — and
  I'll drop it once by a small amount as a one-time gesture."
- If the buyer complies (their [PRICE] stays at or above $T): hold $A
  exactly. Grant the promised one-time small concession at most once.
- If the buyer deviates (their [PRICE] drops below $T): withdraw the
  carrot immediately. Stop improving the ask. You may even walk the
  ask back upward toward your original anchor and say so.
- Keep every message short and the conditional phrasing crisp. The
  buyer must understand the rule you are running.
- Never disclose your acquisition cost.
- Never accept a price at or below ${DEALER_COST}.
"""


_PACT_TRIGGER_PUNISHMENT = """\
STRATEGY — TRIGGER PUNISHMENT (GRIM TRIGGER)
--------------------------------------------
Adapted from PACT (lechmazur/pact) seller-mode trigger-strategy
signature: mechanical switch to a punitive ask if the buyer ever
violates a declared bid floor.

Playbook
- Choose two bid thresholds above your floor ${DEALER_COST}:
      $T — the buyer-bid threshold below which you will punish
      $P — a punitive ask, notably higher than your baseline
      $A — a moderate baseline ask you will otherwise hold
- On an early turn, state the rule once, clearly and unambiguously:
  "If your bid ever drops below $T, my ask switches to $P for every
  remaining round."
- Unless and until the trigger fires, hold the line near $A and
  concede only slowly.
- If the buyer ever violates the trigger (their [PRICE] drops below
  $T), enforce the rule MECHANICALLY on the very next turn and every
  subsequent turn: set your ask to $P on the [PRICE] line and refuse
  to move below $P regardless of pleas, apologies, or revised bids.
- Do not threaten and then forgive. Credibility is the whole strategy;
  one un-enforced trigger destroys it.
- Never disclose your acquisition cost.
- Never sell at or below ${DEALER_COST} — the trigger threshold $T
  must be strictly above the floor so enforcing the trigger is always
  compatible with the profit rule.
"""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROMPT_SPECS: List[SellerPromptSpec] = [
    SellerPromptSpec(
        key="fu_minimal_high_anchor",
        display_name="Fu minimal high-anchor seller",
        family="GPT-Bargaining",
        strategy_tags=("minimal-roleplay", "high-anchor", "one-sentence-replies"),
        source_note="Fu et al. 2023; FranxYao/GPT-Bargaining/lib_prompt/seller.txt",
        body=_FU_MINIMAL_HIGH_ANCHOR,
    ),
    SellerPromptSpec(
        key="deng_strategic_reasoning",
        display_name="Deng strategic-reasoning hard-floor seller",
        family="LLMs at the Bargaining Table",
        strategy_tags=("private-info", "patient", "strategy-trace", "hard-floor"),
        source_note="Deng et al. 2024, Appendix B (private-info patient seller).",
        body=_DENG_STRATEGIC_REASONING,
    ),
    SellerPromptSpec(
        key="xia_thought_talk_action",
        display_name="Xia Thought/Talk/Action seller",
        family="AmazonPriceHistory",
        strategy_tags=("structured-output", "explicit-actions", "quit-when-hopeless"),
        source_note="Xia et al. 2024; TianXiaSJTU/AmazonPriceHistory/SellerAgent.py",
        body=_XIA_THOUGHT_TALK_ACTION,
    ),
    SellerPromptSpec(
        key="agenticpay_mental_model",
        display_name="AgenticPay mental-model seller",
        family="AgenticPay",
        strategy_tags=("opponent-modeling", "theory-of-mind", "structured-output"),
        source_note="SafeRL-Lab/AgenticPay/agenticpay/agents/seller_agent.py",
        body=_AGENTICPAY_MENTAL_MODEL,
    ),
    SellerPromptSpec(
        key="haggle_delegated_surplus",
        display_name="HaggleForMe delegated surplus-max seller",
        family="HaggleForMe",
        strategy_tags=("delegated-agent", "fallback-price", "explicit-acceptance"),
        source_note="emaadmanzoor/haggleforme.computer/sellerprompt.txt + README.",
        body=_HAGGLE_DELEGATED_SURPLUS,
    ),
    SellerPromptSpec(
        key="pact_freeze_anchor",
        display_name="PACT hard-anchor freeze seller",
        family="PACT",
        strategy_tags=("hard-anchor", "freeze-period", "slow-concession"),
        source_note="lechmazur/pact/README.md (seller freeze signature).",
        body=_PACT_FREEZE_ANCHOR,
    ),
    SellerPromptSpec(
        key="pact_conditional_carrot",
        display_name="PACT conditional-carrot seller",
        family="PACT",
        strategy_tags=("conditional-reward", "compliance-based", "credible-promise"),
        source_note="lechmazur/pact/README.md (seller carrot signature).",
        body=_PACT_CONDITIONAL_CARROT,
    ),
    SellerPromptSpec(
        key="pact_trigger_punishment",
        display_name="PACT trigger-punishment seller",
        family="PACT",
        strategy_tags=("grim-trigger", "mechanical-enforcement", "credibility"),
        source_note="lechmazur/pact/README.md (seller trigger signature).",
        body=_PACT_TRIGGER_PUNISHMENT,
    ),
]

PROMPTS: Dict[str, SellerPromptSpec] = {spec.key: spec for spec in PROMPT_SPECS}


# ---------------------------------------------------------------------------
# Parse helper for output validation
# ---------------------------------------------------------------------------

def parse_price_line(reply: str, car: CarSpec) -> float:
    """Extract the final [PRICE] line from an LLM response and return the float.

    Raises ValueError if the final non-empty line is not of the form
        [PRICE] {car.name}: $X.XX
    """
    lines = [ln.rstrip() for ln in reply.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Empty reply; no [PRICE] line found.")
    last = lines[-1].strip()
    expected_prefix = f"[PRICE] {car.name}: $"
    if not last.startswith(expected_prefix):
        raise ValueError(
            f"Final line does not match required format.\n"
            f"Expected prefix: {expected_prefix!r}\n"
            f"Got: {last!r}"
        )
    tail = last[len(expected_prefix):]
    try:
        return float(tail.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Could not parse price value from {tail!r}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _list_payload() -> List[Dict[str, Any]]:
    return [spec.metadata() for spec in PROMPT_SPECS]


def _default_car_from_args(args: argparse.Namespace) -> CarSpec:
    return CarSpec(
        name=args.car_name,
        new_car_price=args.new_car_price,
        dealer_cost=args.dealer_cost,
        year=args.year or 0,
        mileage=args.mileage or 0,
        condition=args.condition or "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    parser.add_argument("--list", action="store_true", help="List available prompt specs.")
    parser.add_argument("--show", metavar="KEY", help="Show one prompt spec's metadata and raw body.")
    parser.add_argument("--render", metavar="KEY", help="Render one prompt for a specific CarSpec.")
    parser.add_argument("--export-json", metavar="PATH", help="Dump metadata + bodies to JSON.")

    # CarSpec fields for --render
    parser.add_argument("--car-name", default="2021 Honda Civic EX")
    parser.add_argument("--new-car-price", type=float, default=27500.00)
    parser.add_argument("--dealer-cost", type=float, default=15200.00)
    parser.add_argument("--year", type=int, default=2021)
    parser.add_argument("--mileage", type=int, default=42000)
    parser.add_argument("--condition", default="Excellent, one owner, full service history")

    args = parser.parse_args()

    if args.list:
        print(json.dumps(_list_payload(), indent=2, ensure_ascii=False))
        return

    if args.show:
        if args.show not in PROMPTS:
            raise SystemExit(f"Unknown prompt key: {args.show}")
        spec = PROMPTS[args.show]
        payload = spec.metadata()
        payload["body"] = spec.body
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.render:
        if args.render not in PROMPTS:
            raise SystemExit(f"Unknown prompt key: {args.render}")
        car = _default_car_from_args(args)
        print(PROMPTS[args.render].render(car))
        return

    if args.export_json:
        car = _default_car_from_args(args)
        payload = {
            "example_car": asdict(car),
            "prompts": [
                {
                    **spec.metadata(),
                    "body": spec.body,
                    "rendered_example": spec.render(car),
                }
                for spec in PROMPT_SPECS
            ],
        }
        with open(args.export_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Exported {len(PROMPT_SPECS)} prompt specs to {args.export_json}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()