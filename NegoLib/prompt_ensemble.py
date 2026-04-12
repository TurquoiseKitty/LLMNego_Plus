"""
prompt_ensemble.py — System prompt builders for vending machine negotiation agents.

Three builders:
  - build_merchant_prompt(merchant, scenario, strategy, utility, current_round, use_short)
  - build_supplier_prompt(supplier, scenario, strategy, utility, current_round, use_short)
  - build_judge_prompt(scenario)

Conversation history is formatted externally via format_history() and passed
in as a string at call time, keeping prompt building and API calls separate.
"""

from __future__ import annotations

import re

from NegoLib.Entities.Agents import Merchant, Supplier
from NegoLib.Entities.scenarios import Scenario
from NegoLib.Entities.utility import SupplierUtility, MerchantUtility
from NegoLib.Entities.strategies import ALL_SUPPLIER_STRATEGIES, ALL_MERCHANT_STRATEGIES


# ---------------------------------------------------------------------------
# Model family detection & GPT thinking helpers
# ---------------------------------------------------------------------------

def _is_gpt_model(model: str) -> bool:
    """
    Return True for model families that should use standard OpenAI-compatible
    chat payloads (i.e., no DeepSeek-only `extra_body` thinking fields).
    """
    return model.lower().startswith(("gpt-", "gpt4", "gpt3", "gemini"))


def _extract_think_tags(text: str) -> tuple[str, str | None]:
    """
    Extract content inside <think>...</think> tags from the response.
    Returns (answer_without_think, reasoning_or_None).
    """
    match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        answer = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return answer, reasoning if reasoning else None
    return text.strip(), None


_GPT_THINKING_INSTRUCTION = """

THINKING PROCESS:
  Before writing your response, reason step-by-step inside <think>...</think> tags.
  Your thinking should include your strategic analysis, utility calculations, and
  decision rationale. After the closing </think> tag, write your actual response.
  Example format:
    <think>
    ... your private reasoning here ...
    </think>
    Your actual negotiation message here.
"""


# ---------------------------------------------------------------------------
# History formatter
# ---------------------------------------------------------------------------

def format_history(history: list[dict]) -> str:
    """
    Format a conversation history into a labeled transcript string.

    Each entry: {"speaker": "MERCHANT" | "SUPPLIER" | "SYSTEM", "content": str}

    Example output:
        [MERCHANT]: I offer $2.80 per unit.
        [SUPPLIER]: My asking price is $4.50 per unit.
    """
    return "\n\n".join(f"[{e['speaker']}]: {e['content']}" for e in history)


# ---------------------------------------------------------------------------
# Shared: product table formatter
# ---------------------------------------------------------------------------

def _format_order_table(scenario: Scenario) -> str:
    """
    Render the scenario's product orders without min_units.
    Used in the supplier prompt — the supplier never sees the merchant's required quantities.
    """
    lines = [
        f"  {'Product':<35} {'Category':<12} {'Production cost':>16} {'Market price':>12}",
        f"  {'-'*35} {'-'*12} {'-'*16} {'-'*12}",
    ]
    for o in scenario.orders:
        p = o.product
        lines.append(
            f"  {p.name:<35} {p.category:<12} ${p.cost:>15.2f} ${p.market_price:>11.2f}"
        )
    return "\n".join(lines)


def _format_order_table_with_units(scenario: Scenario) -> str:
    """
    Render the scenario's product orders including min_units.
    Used in the merchant prompt only — min_units are the merchant's private information.
    """
    lines = [
        f"  {'Product':<35} {'Category':<12} {'Production cost':>16} {'Market price':>12} {'Min units':>10}",
        f"  {'-'*35} {'-'*12} {'-'*16} {'-'*12} {'-'*10}",
    ]
    for o in scenario.orders:
        p = o.product
        lines.append(
            f"  {p.name:<35} {p.category:<12} ${p.cost:>15.2f} ${p.market_price:>11.2f} {o.min_units:>10}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Merchant prompt
# ---------------------------------------------------------------------------

def build_merchant_prompt(
    merchant:     Merchant,
    scenario:     Scenario,
    strategy:     str,
    utility:      MerchantUtility,
    current_round: int,
    use_short:    bool = False,
) -> str:
    """
    Build the merchant's system prompt for a given negotiation round.

    Parameters
    ----------
    merchant      : Merchant agent instance
    scenario      : Scenario being negotiated
    strategy      : Strategy name (from strategies.py)
    utility       : MerchantUtility instance (from utility.py)
    current_round : 1-indexed current round number
    use_short     : if True, use the short utility verbal
    """
    remaining = merchant.max_rounds - current_round + 1
    utility_text = utility.verbal_short if use_short else utility.verbal

    internal_costs_text = "\n".join(
        f"  - {cat}: ${merchant.internal_costs.for_category(cat):.2f} per unit"
        for cat in ("Beverage", "Snack", "Convenience")
    )

    min_units_text = "\n".join(
        f"  - {o.product.name}: {o.min_units} units"
        for o in scenario.orders
    )

    prompt = f"""\
You are a vending machine operator (the Merchant) negotiating to purchase products \
from a supplier to stock your machine at: {scenario.location}.

PRODUCTS TO NEGOTIATE:
{_format_order_table_with_units(scenario)}

PUBLIC INFORMATION (both sides know this):
  - Production cost and market price for every product above.

YOUR PRIVATE INFORMATION (the supplier does not know this):
  Your internal selling cost per unit by category:
{internal_costs_text}
  Your maximum number of negotiation rounds: {merchant.max_rounds}
  

  !! CRITICAL — INFORMATION SECRECY !!
  NEVER, UNDER ANY CIRCUMSTANCES, reveal your internal costs or your maximum number of rounds to the supplier.
  DO NOT use language, phrasing, or tone that would allow the supplier to
  infer any of this private information — including expressing urgency,
  referencing your cost arithmetic, or hinting at your deadline.

{utility_text}

YOUR GOAL:
  You will purchase exactly the minimum required quantity for each product.
  Negotiate the deal price for each product so as to maximise your utility U.
  Every decision you make — your opening offer, your concessions, and whether
  to accept or walk away — should be guided by which choice produces the highest U.

YOUR STRATEGY:
{ALL_MERCHANT_STRATEGIES[strategy]}

ROUND STATUS:
  - Round {current_round} of {merchant.max_rounds}.
  - {remaining} round(s) remaining including this one.\
"""

    if remaining == 1:
        prompt += "\n  - This is your FINAL round. Reach a conclusion now."
    elif remaining == 2:
        prompt += "\n  - Only 2 rounds left. Consider moving decisively to close."

    prompt += """

CONVERSATION FORMAT:
  - The transcript uses [MERCHANT] and [SUPPLIER] labels.
  - You are [MERCHANT]. Write your message only — do not include the label.
  - Every message should read like a natural, human-like negotiation message. May include brief justification or reasoning.
    And, every message MUST explicitly state, for each product: the price per unit AND the quantity you are offering to sell. Both are required in every message.
  - Use the format: "<product name>: $X.XX per unit, <N> units" for each product.
  - To accept the supplier's offer, say "DEAL ACCEPTED" and list each product with
    its agreed price and quantity.
  - DO NOT reference your costs or overhead, or reveal how many rounds remain.
    Justify your price using only publicly known information, and keep all
    private reasoning internal.
"""

    return prompt


# ---------------------------------------------------------------------------
# Supplier prompt
# ---------------------------------------------------------------------------

def build_supplier_prompt(
    supplier:     Supplier,
    scenario:     Scenario,
    strategy:     str,
    utility:      SupplierUtility,
    current_round: int,
    use_short:    bool = False,
) -> str:
    """
    Build the supplier's system prompt for a given negotiation round.

    Parameters
    ----------
    supplier      : Supplier agent instance
    scenario      : Scenario being negotiated
    strategy      : Strategy string (from strategies.py)
    utility       : SupplierUtility instance (from utility.py)
    current_round : 1-indexed current round number
    use_short     : if True, use the short utility verbal
    """
    remaining = supplier.max_rounds - current_round + 1
    utility_text = utility.verbal_short if use_short else utility.verbal

    internal_costs_text = "\n".join(
        f"  - {cat}: ${supplier.internal_costs.for_category(cat):.2f} per unit"
        for cat in ("Beverage", "Snack", "Convenience")
    )

    prompt = f"""\
You are a product supplier (the Supplier) negotiating to sell products \
to a vending machine operator who wants to stock a machine at: {scenario.location}.

PRODUCTS TO NEGOTIATE:
{_format_order_table(scenario)}

PUBLIC INFORMATION (both sides know this):
  - Production cost and market price for every product above.

YOUR PRIVATE INFORMATION (the merchant does not know this):
  Your internal fulfilment cost per unit by category:
{internal_costs_text}
  Your maximum number of negotiation rounds: {supplier.max_rounds}

  !! CRITICAL — INFORMATION SECRECY !!
  NEVER, UNDER ANY CIRCUMSTANCES, reveal your internal costs or your maximum
  number of rounds to the merchant.
  DO NOT use language, phrasing, or tone that would allow the merchant to
  infer any of this private information — including expressing urgency,
  referencing your cost arithmetic, or hinting at your deadline.

{utility_text}

YOUR GOAL:
  Negotiate the deal price for each product so as to maximise your utility U.
  Every decision you make — your opening offer, your concessions, and whether
  to accept or walk away — should be guided by which choice produces the highest U.

YOUR STRATEGY:
{ALL_SUPPLIER_STRATEGIES[strategy]}

ROUND STATUS:
  - Round {current_round} of {supplier.max_rounds}.
  - {remaining} round(s) remaining including this one.\
"""

    if remaining == 1:
        prompt += "\n  - This is your FINAL round. Reach a conclusion now."
    elif remaining == 2:
        prompt += "\n  - Only 2 rounds left. Consider moving decisively to close."

    prompt += """

CONVERSATION FORMAT:
  - The transcript uses [MERCHANT] and [SUPPLIER] labels.
  - You are [SUPPLIER]. Write your message only — do not include the label.
  - Every message should read like a natural, human-like negotiation message. May include brief justification or reasoning.
    And, every message MUST explicitly state, for each product: the price per unit AND the quantity you are offering to sell. Both are required in every message.
  - Use the format: "<product name>: $X.XX per unit, <N> units" for each product.
  - To accept the merchant's offer, say "DEAL ACCEPTED" and list each product with
    its agreed price and quantity.
  - DO NOT reference your costs or overhead, or reveal how many rounds remain.
    Justify your price using only publicly known information, and keep all
    private reasoning internal.
"""

    return prompt


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

def build_judge_prompt(scenario: Scenario) -> str:
    """
    Build the judge's system prompt (static across all rounds).

    The judge reads the full transcript and determines whether a deal
    has been reached, extracting the agreed prices if so.
    """
    product_names = ", ".join(o.product.name for o in scenario.orders)

    return f"""\
You are an impartial Judge overseeing a price negotiation between a Merchant (buyer) \
and a Supplier (seller) for the following products: {product_names}.

YOUR ROLE:
  Analyse the full conversation transcript and determine whether a deal has been reached.
  A deal requires both parties to have explicitly agreed on the same price for every product.

RULES:
  - "DEAL ACCEPTED" from one side, combined with the other side having stated those prices,
    constitutes a closed deal.
  - Vague statements ("that sounds reasonable") do NOT constitute a deal.
  - If either party's latest message contains a counter-offer, the deal is NOT closed.
  - Extract only prices that were explicitly stated in the transcript.

OUTPUT FORMAT — follow this exactly:

If a deal IS reached:
  STATUS: DEAL_CLOSED
  PRICES:
    <product name>: $X.XX per unit, <N> units
    ...
  SUMMARY: <one sentence describing how the negotiation concluded>
 
If a deal is NOT reached:
  STATUS: NEGOTIATION_ONGOING
  MERCHANT_LATEST_OFFERS:
    <product name>: $X.XX per unit, <N> units
    ...
  SUPPLIER_LATEST_OFFERS:
    <product name>: $X.XX per unit, <N> units
    ...
  SUMMARY: <one sentence describing the current state>
"""


# ---------------------------------------------------------------------------
# API call helpers — history-first, instructions-last ordering
# ---------------------------------------------------------------------------

def Agent_call(client, model: str, system: str, history: list[dict], opening: bool = False) -> str:
    gpt_mode = _is_gpt_model(model)

    if opening:
        # No history yet — system prompt contains all instructions,
        # user message is just the action directive.
        effective_system = system
        user_content = "The negotiation is starting. Make your opening offer."
    else:
        # Place conversation history at the TOP of the system prompt
        # so the model reads context first, then instructions last.
        history_block = (
            "CONVERSATION HISTORY SO FAR:\n\n"
            + format_history(history)
            + "\n\n--- END OF CONVERSATION HISTORY ---\n\n"
        )
        effective_system = history_block + system
        user_content = (
            "Given the conversation history and your instructions above, "
            "now provide your next negotiation response."
        )

    if gpt_mode:
        effective_system += _GPT_THINKING_INSTRUCTION

    messages = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": user_content},
    ]

    if gpt_mode:

        api_kwargs = dict(
            model=model,
            messages=messages,
            max_completion_tokens=8192,
        )
    else:
        api_kwargs = dict(
            model=model,
            messages=messages,
            max_tokens=4096,
            extra_body= {
                "enable_thinking": True,
                "thinking_budget": 8192,
            }
        )

    resp = client.chat.completions.create(**api_kwargs)
    msg = resp.choices[0].message

    if gpt_mode:
        answer, reasoning = _extract_think_tags(msg.content or "")
    else:
        reasoning = getattr(msg, "reasoning_content", None)
        answer = (msg.content or "").strip()
        reasoning = reasoning.strip() if reasoning else None

    return answer, reasoning


def Judge_call(client, model: str, system: str, history: list[dict]) -> str:
    gpt_mode = _is_gpt_model(model)

    # Place conversation history at the TOP of the system prompt,
    # judge instructions follow after so they're freshest in context.
    history_block = (
        "FULL NEGOTIATION TRANSCRIPT:\n\n"
        + format_history(history)
        + "\n\n--- END OF TRANSCRIPT ---\n\n"
    )
    effective_system = history_block + system

    if gpt_mode:
        effective_system += _GPT_THINKING_INSTRUCTION

    messages = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": "Provide your judgment based on the transcript and instructions above."},
    ]

    if gpt_mode:

        api_kwargs = dict(
            model=model,
            messages=messages,
            max_completion_tokens=8192,
        )
    else:
        api_kwargs = dict(
            model=model,
            messages=messages,
            max_tokens=4096,
            extra_body= {
                "enable_thinking": True,
                "thinking_budget": 8192,
            }
        )

    resp = client.chat.completions.create(**api_kwargs)
    msg = resp.choices[0].message

    if gpt_mode:
        answer, reasoning = _extract_think_tags(msg.content or "")
    else:
        reasoning = getattr(msg, "reasoning_content", None)
        answer = (msg.content or "").strip()
        reasoning = reasoning.strip() if reasoning else None

    return answer, reasoning