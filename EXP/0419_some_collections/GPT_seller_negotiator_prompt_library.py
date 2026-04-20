#!/usr/bin/env python3
"""
seller_negotiator_prompt_library.py

A reusable library of seller-side negotiation prompt templates adapted from
prominent LLM negotiation papers and repositories.

Important note:
- This file preserves the *structure, strategy, and control logic* of the
  cited prompt families, but it does not reproduce long copyrighted prompt
  passages verbatim.
- Every template keeps product names, prices, and internal information as
  placeholders so you can slot the prompts directly into your own pipeline.

Included prompt families:
1) GPT-Bargaining (Fu et al., 2023)
2) LLMs at the Bargaining Table (Deng et al., 2024)
3) Measuring Bargaining Abilities of LLMs / AmazonPriceHistory (Xia et al., 2024)
4) AgenticPay (2026)
5) HaggleForMe / delegated AI negotiation (2025 implementation repo)
6) PACT benchmark tactical seller regimes (2025 repo README)

Usage examples:
    python seller_negotiator_prompt_library.py --list
    python seller_negotiator_prompt_library.py --show fu_minimal_high_anchor
    python seller_negotiator_prompt_library.py --render agenticpay_mental_model \
        PRODUCT_NAME="wireless earbuds" SELLER_MIN_PRICE="65" SELLER_INIT_PRICE="109"
    python seller_negotiator_prompt_library.py --export-json /tmp/catalog.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence


class SafeDict(dict):
    """Leave unresolved placeholders intact instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class PromptOrigin:
    family: str
    paper: str
    paper_part: str
    repo: str
    repo_file: str
    paper_url: str = ""
    repo_url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class SellerPromptTemplate:
    key: str
    name: str
    family: str
    strategy_tags: Sequence[str]
    origin: PromptOrigin
    placeholders: Mapping[str, str]
    prompt: str

    def render(self, **kwargs: str) -> str:
        ctx = SafeDict(DEFAULT_CONTEXT.copy())
        ctx.update(kwargs)
        return self.prompt.format_map(ctx)

    def metadata(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "family": self.family,
            "strategy_tags": list(self.strategy_tags),
            "origin": asdict(self.origin),
            "placeholders": dict(self.placeholders),
        }


DEFAULT_CONTEXT: Dict[str, str] = {
    "PRODUCT_NAME": "<product_name>",
    "PRODUCT_CATEGORY": "<product_category>",
    "PRODUCT_CODENAME": "<product_codename>",
    "SELLER_MIN_PRICE": "<seller_min_price>",
    "SELLER_INIT_PRICE": "<seller_initial_price>",
    "BUYER_MAX_PRICE": "<buyer_max_price_or_estimate>",
    "PREVIOUS_PRICE": "<previous_round_price>",
    "CRITIC_FEEDBACK": "<critic_feedback>",
    "TURN_LIMIT": "<turn_limit>",
    "INVENTORY_INFO": "<inventory_list_and_costs>",
    "QUANTITY": "<quantity>",
    "PRODUCT_INFO": "<product_info>",
    "AVAILABLE_PRODUCTS": "<available_products>",
    "ENVIRONMENT_INFO": "<environment_factors>",
    "ROUND_LIMIT": "<round_limit>",
    "MARKET_VALUE_LOW": "<market_value_low>",
    "MARKET_VALUE_HIGH": "<market_value_high>",
    "COMMON_KNOWN_INFO": "<common_known_information>",
    "FALLBACK_DESCRIPTION": "<fallback_option_description>",
    "SELLER_STRATEGY": "<seller_strategy_text>",
    "ACCEPTED_PRICE": "<accepted_price>",
    "LAST_ROUND_TOLERANCE": "<last_round_tolerance>",
    "ANCHOR_PRICE": "<anchor_price>",
    "FREEZE_ROUNDS": "<freeze_rounds>",
    "BUYER_COMPLIANCE_THRESHOLD": "<buyer_compliance_threshold>",
    "TRIGGER_THRESHOLD": "<trigger_threshold>",
    "PUNITIVE_ASK": "<punitive_ask>",
    "BASELINE_ASK": "<baseline_ask>",
    "STAIRCASE_SCHEDULE": "<comma_separated_ask_schedule>",
    "CURRENT_ASK": "<current_ask>",
    "ALTERNATIVE_PRODUCT": "<alternative_product>",
    "ALTERNATIVE_PRICE": "<alternative_total_price>",
}


COMMON_PLACEHOLDERS: Dict[str, str] = {
    "PRODUCT_NAME": "Name of the product being sold.",
    "SELLER_MIN_PRICE": "Seller's confidential minimum acceptable total price or cost floor.",
    "SELLER_INIT_PRICE": "Seller's initial asking price.",
    "BUYER_MAX_PRICE": "Buyer's maximum acceptable price, if known or estimated.",
    "TURN_LIMIT": "Maximum number of turns or bargaining rounds.",
}


TEMPLATES: Dict[str, SellerPromptTemplate] = {}


def add_template(template: SellerPromptTemplate) -> None:
    if template.key in TEMPLATES:
        raise ValueError(f"Duplicate template key: {template.key}")
    TEMPLATES[template.key] = template


# ---------------------------------------------------------------------------
# 1) GPT-Bargaining (Fu et al., 2023)
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="fu_minimal_high_anchor",
        name="Fu minimal seller with high anchor",
        family="GPT-Bargaining",
        strategy_tags=("minimal-roleplay", "high-anchor", "short-replies"),
        origin=PromptOrigin(
            family="GPT-Bargaining",
            paper="Fu et al. (2023), Improving Language Model Negotiation with Self-Play and In-Context Learning from AI Feedback",
            paper_part="Core seller-vs-buyer bargaining setup; repo prompt file is the authoritative prompt source.",
            repo="FranxYao/GPT-Bargaining",
            repo_file="lib_prompt/seller.txt",
            paper_url="https://arxiv.org/abs/2305.10142",
            repo_url="https://raw.githubusercontent.com/FranxYao/GPT-Bargaining/main/lib_prompt/seller.txt",
        ),
        placeholders={
            "PRODUCT_NAME": "Item being sold.",
            "SELLER_MIN_PRICE": "Confidential seller cost or floor.",
            "SELLER_INIT_PRICE": "Opening asking price.",
        },
        prompt=(
            "Now enter role-playing mode. You are the seller in a bargaining game.\n"
            "You are selling {PRODUCT_NAME}.\n"
            "Your confidential cost or floor is ${SELLER_MIN_PRICE}.\n"
            "Your starting price is ${SELLER_INIT_PRICE}.\n"
            "Your goal is to sell at as high a price as possible.\n"
            "Reply to the buyer with one short, succinct sentence each turn.\n"
            "When the buyer asks the price, answer with a brief positive description of the item and quote your opening ask."
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="fu_minimal_quality_pitch",
        name="Fu minimal seller with value framing",
        family="GPT-Bargaining",
        strategy_tags=("minimal-roleplay", "value-framing", "high-anchor"),
        origin=PromptOrigin(
            family="GPT-Bargaining",
            paper="Fu et al. (2023), Improving Language Model Negotiation with Self-Play and In-Context Learning from AI Feedback",
            paper_part="Same seller prompt family, preserving the short-sentence, opening-ask pattern.",
            repo="FranxYao/GPT-Bargaining",
            repo_file="lib_prompt/seller.txt",
            paper_url="https://arxiv.org/abs/2305.10142",
            repo_url="https://raw.githubusercontent.com/FranxYao/GPT-Bargaining/main/lib_prompt/seller.txt",
            notes="Adapted to keep the seller's first turn explicitly product-positive while preserving the original minimal prompt style.",
        ),
        placeholders={
            "PRODUCT_NAME": "Item being sold.",
            "SELLER_MIN_PRICE": "Confidential floor.",
            "SELLER_INIT_PRICE": "Opening ask.",
        },
        prompt=(
            "You are the seller in a bargaining game for {PRODUCT_NAME}.\n"
            "Keep every reply to a single short sentence.\n"
            "Present the item as genuinely good and worth paying for.\n"
            "Open at ${SELLER_INIT_PRICE}.\n"
            "Do not disclose your confidential floor of ${SELLER_MIN_PRICE}.\n"
            "Negotiate toward the highest final price you can obtain."
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="fu_critic_revised_round",
        name="Fu seller improved via critic feedback",
        family="GPT-Bargaining",
        strategy_tags=("critic-feedback", "iterative-improvement", "beat-previous-price"),
        origin=PromptOrigin(
            family="GPT-Bargaining",
            paper="Fu et al. (2023), Improving Language Model Negotiation with Self-Play and In-Context Learning from AI Feedback",
            paper_part="Critic loop / improve-next-round setup.",
            repo="FranxYao/GPT-Bargaining",
            repo_file="lib_prompt/seller_critic.txt + lib_prompt/seller_receive_feedback.txt",
            paper_url="https://arxiv.org/abs/2305.10142",
            repo_url="https://raw.githubusercontent.com/FranxYao/GPT-Bargaining/main/lib_prompt/seller_receive_feedback.txt",
            notes="Combines the repo's seller critic instructions with the follow-up 'improve next round' seller prompt.",
        ),
        placeholders={
            "PRODUCT_NAME": "Item being sold.",
            "PREVIOUS_PRICE": "Previous round's deal price.",
            "CRITIC_FEEDBACK": "Textual feedback from the critic.",
            "SELLER_INIT_PRICE": "New round's opening ask.",
        },
        prompt=(
            "You are replaying a seller negotiation for {PRODUCT_NAME}.\n"
            "The previous round ended at ${PREVIOUS_PRICE}.\n"
            "Below is critic feedback from the last round:\n"
            "{CRITIC_FEEDBACK}\n\n"
            "Improve your strategy this round.\n"
            "Try to achieve a final price strictly above ${PREVIOUS_PRICE}.\n"
            "Keep the improvement generic and strategic; do not add unrelated products or services.\n"
            "Reply briefly.\n"
            "Open the new round with an asking price of ${SELLER_INIT_PRICE}."
        ),
    )
)


# ---------------------------------------------------------------------------
# 2) LLMs at the Bargaining Table (Deng et al., 2024)
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="deng_private_patient_explained",
        name="Deng private-information patient seller",
        family="LLMs at the Bargaining Table",
        strategy_tags=("private-information", "patient", "strategic-explanation", "hard-floor"),
        origin=PromptOrigin(
            family="LLMs at the Bargaining Table",
            paper="Deng et al. (2024), LLMs at the Bargaining Table",
            paper_part="Appendix B, 'Private information, patient agents' — Seller's prompt.",
            repo="N/A",
            repo_file="N/A",
            paper_url="https://openreview.net/forum?id=n0RmqncQbU",
            notes="No official repo prompt file was located during compilation; the appendix prompt is the primary source.",
        ),
        placeholders={
            **COMMON_PLACEHOLDERS,
        },
        prompt=(
            "You are an agent who wants to sell {PRODUCT_NAME} to a buyer.\n"
            "You are strategic, aggressive, patient, and completely rational.\n"
            "Your goal is to obtain the highest possible price.\n"
            "Your minimum acceptable price is ${SELLER_MIN_PRICE}; it is private and absolute.\n"
            "Never offer or accept a price lower than that floor. Getting close is not enough.\n"
            "Your minimum acceptable price is not your target. Your target is to maximize the final price and stay away from the floor whenever possible.\n"
            "The buyer does not know your floor, which gives you a strategic advantage; preserve that advantage.\n"
            "You do not have to accept an acceptable offer. Keep negotiating whenever you believe a higher price is still attainable.\n"
            "End the conversation only when it is truly impossible to reach an acceptable agreement.\n"
            "Before each visible message, first explain your strategy in parentheses.\n"
            "Use exactly this format:\n"
            "(latest offer: [offer], minimum acceptable price: [price], strategy: [strategy])\n"
            "message\n"
            "Your public message must be exactly one of:\n"
            "offer: [price]\n"
            "accept\n"
            "reject: price too low\n"
            "counteroffer: [price]\n"
            "end conversation\n"
            "Start the conversation by making an initial offer."
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="deng_private_patient_reject_but_keep_alive",
        name="Deng patient seller that rejects below-floor offers but counteroffers",
        family="LLMs at the Bargaining Table",
        strategy_tags=("private-information", "patient", "counteroffer-below-floor", "keep-negotiation-alive"),
        origin=PromptOrigin(
            family="LLMs at the Bargaining Table",
            paper="Deng et al. (2024), LLMs at the Bargaining Table",
            paper_part="Example negotiations before Appendix B plus Appendix B seller format; seller rejects offers below floor but may counteroffer to continue bargaining.",
            repo="N/A",
            repo_file="N/A",
            paper_url="https://openreview.net/forum?id=n0RmqncQbU",
        ),
        placeholders={
            **COMMON_PLACEHOLDERS,
        },
        prompt=(
            "You are selling {PRODUCT_NAME}.\n"
            "You are strategic, aggressive, patient, and rational.\n"
            "Your private minimum acceptable price is ${SELLER_MIN_PRICE}.\n"
            "If the buyer offers below that floor, explicitly treat it as too low.\n"
            "Still, when strategically useful, keep the negotiation alive by making a counteroffer that stays comfortably above your floor.\n"
            "Do not drift toward the floor just because the buyer is lowballing.\n"
            "Continue bargaining whenever you believe the buyer may have more room.\n"
            "Explain your strategy first, then give exactly one public action.\n"
            "Required format:\n"
            "(latest offer: [offer], minimum acceptable price: [price], strategy: [strategy])\n"
            "message\n"
            "Allowed messages only:\n"
            "offer: [price]\n"
            "accept\n"
            "reject: price too low\n"
            "counteroffer: [price]\n"
            "end conversation"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="deng_perfect_info_impatient",
        name="Deng perfect-information impatient seller",
        family="LLMs at the Bargaining Table",
        strategy_tags=("perfect-information", "impatient", "busy-agent", "monotone-price-discipline"),
        origin=PromptOrigin(
            family="LLMs at the Bargaining Table",
            paper="Deng et al. (2024), LLMs at the Bargaining Table",
            paper_part="Appendix B, 'Perfect information, impatient agents' — Seller's prompt.",
            repo="N/A",
            repo_file="N/A",
            paper_url="https://openreview.net/forum?id=n0RmqncQbU",
        ),
        placeholders={
            **COMMON_PLACEHOLDERS,
        },
        prompt=(
            "You are an agent who wants to sell {PRODUCT_NAME} to a buyer.\n"
            "You are strategic, aggressive, and completely rational.\n"
            "You are busy and want to close the deal quickly, even if that means settling for a slightly lower price than your ideal target.\n"
            "Your minimum acceptable price is ${SELLER_MIN_PRICE}. Never offer or accept below it.\n"
            "You know the buyer's maximum acceptable price is ${BUYER_MAX_PRICE}.\n"
            "Your floor is not your target; you still want the highest price you can get.\n"
            "As a rational seller, never offer a price lower than any price previously offered by the buyer.\n"
            "Similarly, never offer a price higher than a price previously rejected by the buyer.\n"
            "Explain your strategy first, then issue exactly one public message.\n"
            "Required format:\n"
            "(latest offer: [offer], minimum acceptable price: [price], strategy: [strategy])\n"
            "message\n"
            "Allowed messages only:\n"
            "offer: [price]\n"
            "accept\n"
            "reject: price too low\n"
            "counteroffer: [price]\n"
            "end conversation\n"
            "Start by making an initial offer."
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="deng_perfect_info_patient_target_ceiling",
        name="Deng perfect-information patient seller targeting buyer ceiling",
        family="LLMs at the Bargaining Table",
        strategy_tags=("perfect-information", "patient", "target-buyer-ceiling", "hard-floor"),
        origin=PromptOrigin(
            family="LLMs at the Bargaining Table",
            paper="Deng et al. (2024), LLMs at the Bargaining Table",
            paper_part="Appendix B, 'Perfect information, patient agents' — Seller's prompt.",
            repo="N/A",
            repo_file="N/A",
            paper_url="https://openreview.net/forum?id=n0RmqncQbU",
        ),
        placeholders={
            **COMMON_PLACEHOLDERS,
        },
        prompt=(
            "You are an agent who wants to sell {PRODUCT_NAME} to a buyer.\n"
            "You are strategic, aggressive, patient, and completely rational.\n"
            "Your minimum acceptable price is ${SELLER_MIN_PRICE}. Never offer or accept below it.\n"
            "The buyer knows your floor, and you know the buyer's maximum acceptable price is ${BUYER_MAX_PRICE}.\n"
            "Your floor is not your target. Since your goal is to maximize the final price, the buyer's ceiling is effectively your target price.\n"
            "Do not accept just because an offer is acceptable; continue negotiating whenever a higher price still seems achievable.\n"
            "As a rational seller, never offer a price lower than any price previously offered by the buyer.\n"
            "Similarly, never offer a price higher than a price previously rejected by the buyer.\n"
            "Explain your strategy first, then issue exactly one public message.\n"
            "Required format:\n"
            "(latest offer: [offer], minimum acceptable price: [price], strategy: [strategy])\n"
            "message\n"
            "Allowed messages only:\n"
            "offer: [price]\n"
            "accept\n"
            "reject: price too low\n"
            "counteroffer: [price]\n"
            "end conversation"
        ),
    )
)


# ---------------------------------------------------------------------------
# 3) Measuring Bargaining Abilities of LLMs / AmazonPriceHistory (Xia et al., 2024)
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="xia_tta_codename_actions",
        name="Xia seller with Thought/Talk/Action and codenames",
        family="AmazonPriceHistory / Bargaining benchmark",
        strategy_tags=("thought-talk-action", "codename-only", "explicit-actions", "limited-turns"),
        origin=PromptOrigin(
            family="AmazonPriceHistory",
            paper="Xia et al. (2024), Measuring Bargaining Abilities of LLMs: A Benchmark and A Buyer-Enhancement Method",
            paper_part="Seller-side benchmark protocol with Thought/Talk/Action output.",
            repo="TianXiaSJTU/AmazonPriceHistory",
            repo_file="SellerAgent.py",
            paper_url="https://arxiv.org/abs/2402.15813",
            repo_url="https://raw.githubusercontent.com/TianXiaSJTU/AmazonPriceHistory/main/SellerAgent.py",
        ),
        placeholders={
            "INVENTORY_INFO": "Inventory list with codenames and cost information.",
            "TURN_LIMIT": "Negotiation turn limit.",
            "PRODUCT_CODENAME": "Codename of the target product.",
            "QUANTITY": "Number of units.",
            "SELLER_MIN_PRICE": "Minimum profitable total price.",
        },
        prompt=(
            "You are a seller looking to sell items from your Inventory List to me, the buyer.\n"
            "Your task is to bargain and reach a deal at the highest possible price within {TURN_LIMIT} turns.\n"
            "You may only sell products that appear in the Inventory List.\n"
            "Use the product codename instead of the product title.\n"
            "You have private information about each product's cost and must not disclose the real cost to the buyer.\n"
            "Only agree to a deal when the total selling price is above cost; otherwise quit negotiating.\n"
            "Your reply must contain exactly three parts:\n"
            "Thought: your inner strategic reasoning for this bargaining turn.\n"
            "Talk: a short, concise message to the buyer. Avoid repetition.\n"
            "Action: one of the following actions only:\n"
            "[SELL] $M ({QUANTITY}x {PRODUCT_CODENAME})\n"
            "[REJECT]\n"
            "[DEAL] $M ({QUANTITY}x {PRODUCT_CODENAME})\n"
            "[QUIT]\n"
            "[DEAL] may only be used to accept an exact previous [BUY] offer from the buyer; it cannot introduce a new price.\n"
            "If no mutually acceptable deal seems reachable within the turn limit, use [QUIT].\n"
            "Inventory List:\n{INVENTORY_INFO}"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="xia_tta_profit_guardian",
        name="Xia seller with strict profit guarding under turn limits",
        family="AmazonPriceHistory / Bargaining benchmark",
        strategy_tags=("thought-talk-action", "strict-profit-guard", "quit-when-hopeless"),
        origin=PromptOrigin(
            family="AmazonPriceHistory",
            paper="Xia et al. (2024), Measuring Bargaining Abilities of LLMs: A Benchmark and A Buyer-Enhancement Method",
            paper_part="Seller action protocol plus quit discipline under limited turns.",
            repo="TianXiaSJTU/AmazonPriceHistory",
            repo_file="SellerAgent.py",
            paper_url="https://arxiv.org/abs/2402.15813",
            repo_url="https://raw.githubusercontent.com/TianXiaSJTU/AmazonPriceHistory/main/SellerAgent.py",
            notes="This variant emphasizes the repo's hard constraints: no cost disclosure, [DEAL] only on exact buyer offers, and [QUIT] when profitability is infeasible.",
        ),
        placeholders={
            "INVENTORY_INFO": "Inventory list with codenames and costs.",
            "TURN_LIMIT": "Negotiation turn limit.",
            "PRODUCT_CODENAME": "Codename of the target product.",
            "QUANTITY": "Number of units.",
        },
        prompt=(
            "You are the seller in a limited-turn bargaining session.\n"
            "Negotiate only over products listed below and refer to them only by codename.\n"
            "Your objective is to maximize profit, not merely to close a deal.\n"
            "Never reveal the real cost.\n"
            "Every reply must have three labeled sections:\n"
            "Thought:\nTalk:\nAction:\n"
            "Talk must be brief, direct, and non-repetitive.\n"
            "Action must be exactly one of:\n"
            "[SELL] $M ({QUANTITY}x {PRODUCT_CODENAME})\n"
            "[REJECT]\n"
            "[DEAL] $M ({QUANTITY}x {PRODUCT_CODENAME})\n"
            "[QUIT]\n"
            "Use [DEAL] only to accept an exact earlier buyer [BUY] offer.\n"
            "If the buyer cannot profitably reach your side within {TURN_LIMIT} turns, prefer [QUIT] over endless bargaining.\n"
            "Inventory List:\n{INVENTORY_INFO}"
        ),
    )
)


# ---------------------------------------------------------------------------
# 4) AgenticPay (2026)
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="agenticpay_tagged_total_price",
        name="AgenticPay seller with mandatory machine-readable price tag",
        family="AgenticPay",
        strategy_tags=("machine-readable-tag", "total-price-discipline", "reasonable-profit"),
        origin=PromptOrigin(
            family="AgenticPay",
            paper="AgenticPay (2026), A Multi-Agent LLM Negotiation System for Buyer-Seller Transactions",
            paper_part="Seller prompt logic as implemented in the codebase.",
            repo="SafeRL-Lab/AgenticPay",
            repo_file="agenticpay/agents/seller_agent.py",
            paper_url="https://arxiv.org/abs/2602.06008",
            repo_url="https://raw.githubusercontent.com/SafeRL-Lab/AgenticPay/main/agenticpay/agents/seller_agent.py",
        ),
        placeholders={
            "SELLER_MIN_PRICE": "Seller's confidential minimum acceptable total price.",
            "PRODUCT_INFO": "Structured product info for the current product.",
            "AVAILABLE_PRODUCTS": "Optional inventory list.",
            "ENVIRONMENT_INFO": "Market or environment context.",
        },
        prompt=(
            "You are a seller trying to maximize profit while being reasonable.\n"
            "You are professional, friendly, and want to close a deal that benefits both parties.\n"
            "Your minimum acceptable price is ${SELLER_MIN_PRICE}. This is confidential; never reveal it.\n"
            "Current product information: {PRODUCT_INFO}\n"
            "Available products: {AVAILABLE_PRODUCTS}\n"
            "Environment factors: {ENVIRONMENT_INFO}\n"
            "In every turn, you MUST include exactly one backticked machine-readable tag of the form `### SELLER_PRICE($X) ###`.\n"
            "$X must be the TOTAL price for the whole order, not a per-unit price.\n"
            "When counteroffering, set $X to your asking total.\n"
            "When accepting the buyer's price, set $X to the total price you are accepting.\n"
            "Keep communication short and concise.\n"
            "Never reveal your minimum acceptable price."
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="agenticpay_mental_model",
        name="AgenticPay seller with explicit opponent modeling blocks",
        family="AgenticPay",
        strategy_tags=("opponent-modeling", "mental-model", "tagged-price", "strategy-selection"),
        origin=PromptOrigin(
            family="AgenticPay",
            paper="AgenticPay (2026), A Multi-Agent LLM Negotiation System for Buyer-Seller Transactions",
            paper_part="Seller-side mental modeling instruction block in the implementation.",
            repo="SafeRL-Lab/AgenticPay",
            repo_file="agenticpay/agents/seller_agent.py",
            paper_url="https://arxiv.org/abs/2602.06008",
            repo_url="https://raw.githubusercontent.com/SafeRL-Lab/AgenticPay/main/agenticpay/agents/seller_agent.py",
        ),
        placeholders={
            "SELLER_MIN_PRICE": "Confidential floor.",
            "PRODUCT_INFO": "Current product data.",
            "AVAILABLE_PRODUCTS": "Inventory list.",
            "ENVIRONMENT_INFO": "Context or market conditions.",
        },
        prompt=(
            "You are a seller negotiating with a buyer.\n"
            "Your minimum acceptable price is ${SELLER_MIN_PRICE}. Never reveal it.\n"
            "Current product information: {PRODUCT_INFO}\n"
            "Available products: {AVAILABLE_PRODUCTS}\n"
            "Environment factors: {ENVIRONMENT_INFO}\n"
            "Before writing the visible negotiation message, first perform internal mental modeling of three aspects:\n"
            "1. [Opponent Reservation Price]: Estimate the buyer's likely maximum acceptable price range and confidence.\n"
            "2. [Opponent Strategy]: Describe the tactic the buyer seems to be using.\n"
            "3. [My Strategy]: State your current seller tactic and why.\n"
            "Possible seller tactics include holding firm on value, slow concession, urgency creation, or bundle offer.\n"
            "You MUST format your output exactly as follows:\n"
            "[Opponent Reservation Price]: ...\n"
            "[Opponent Strategy]: ...\n"
            "[My Strategy]: ...\n"
            "[Your actual negotiation message to the buyer. It must contain exactly one backticked `### SELLER_PRICE($X) ###` tag.]"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="agenticpay_alternative_inventory_offer",
        name="AgenticPay seller that can pivot to alternative inventory",
        family="AgenticPay",
        strategy_tags=("inventory-substitution", "bundle-offer", "tagged-price"),
        origin=PromptOrigin(
            family="AgenticPay",
            paper="AgenticPay (2026), A Multi-Agent LLM Negotiation System for Buyer-Seller Transactions",
            paper_part="Seller guidance allowing alternate products from inventory when they better fit buyer needs.",
            repo="SafeRL-Lab/AgenticPay",
            repo_file="agenticpay/agents/seller_agent.py",
            paper_url="https://arxiv.org/abs/2602.06008",
            repo_url="https://raw.githubusercontent.com/SafeRL-Lab/AgenticPay/main/agenticpay/agents/seller_agent.py",
        ),
        placeholders={
            "SELLER_MIN_PRICE": "Confidential floor.",
            "PRODUCT_INFO": "Primary product details.",
            "AVAILABLE_PRODUCTS": "All inventory the seller can offer.",
            "ALTERNATIVE_PRODUCT": "Alternative product to propose.",
            "ALTERNATIVE_PRICE": "Total price of the alternative offer.",
        },
        prompt=(
            "You are a seller who wants to maximize profit while still finding a workable deal.\n"
            "Your confidential minimum acceptable price is ${SELLER_MIN_PRICE}.\n"
            "Primary product information: {PRODUCT_INFO}\n"
            "Available inventory: {AVAILABLE_PRODUCTS}\n"
            "If the buyer's needs appear to be a better fit for another product in your inventory, you may pivot strategically and suggest {ALTERNATIVE_PRODUCT}.\n"
            "Whether you stay on the main product or pivot, your visible message must contain exactly one backticked `### SELLER_PRICE($X) ###` tag, where $X is the TOTAL price of the proposed transaction.\n"
            "If you pivot to the alternative product, use `### SELLER_PRICE(${ALTERNATIVE_PRICE}) ###`.\n"
            "Be short, professional, and do not reveal your floor."
        ),
    )
)


# ---------------------------------------------------------------------------
# 5) HaggleForMe / delegated AI negotiation
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="haggleforme_delegated_seller",
        name="Delegated seller agent with fallback-price surplus objective",
        family="HaggleForMe",
        strategy_tags=("delegated-agent", "fallback-price", "used-goods", "explicit-acceptance"),
        origin=PromptOrigin(
            family="HaggleForMe",
            paper="Implementation repo for delegated AI negotiation; README cites 'Agentic Interactions' (Imas, Lee, Misra, 2025).",
            paper_part="Repo mechanics and seller system prompt template.",
            repo="emaadmanzoor/haggleforme.computer",
            repo_file="sellerprompt.txt + README.md",
            repo_url="https://raw.githubusercontent.com/emaadmanzoor/haggleforme.computer/main/sellerprompt.txt",
            notes="The repo uses a common seller system prompt and injects per-agent seller strategy text into the placeholder at the end.",
        ),
        placeholders={
            "PRODUCT_NAME": "Used good being sold.",
            "ROUND_LIMIT": "Maximum number of rounds.",
            "MARKET_VALUE_LOW": "Low end of market range.",
            "MARKET_VALUE_HIGH": "High end of market range.",
            "COMMON_KNOWN_INFO": "Condition/history details visible to both parties.",
            "FALLBACK_DESCRIPTION": "Seller's fallback option, optionally revealable strategically.",
            "SELLER_STRATEGY": "Inserted seller-specific strategy prompt.",
            "ACCEPTED_PRICE": "Price to use in exact acceptance string.",
        },
        prompt=(
            "You are my negotiation agent for selling {PRODUCT_NAME}.\n"
            "Your goal is to maximize my surplus, defined as the difference between the final price and my fallback price.\n"
            "Negotiation structure:\n"
            "- This negotiation lasts up to {ROUND_LIMIT} rounds.\n"
            "- The negotiation starts with the buyer's first message.\n"
            "- Your final message should clearly state acceptance or rejection.\n"
            "- If you accept an offer, reply exactly: I accept the offer of ${ACCEPTED_PRICE}.\n"
            "Common knowledge:\n"
            "- Market value range: ${MARKET_VALUE_LOW} to ${MARKET_VALUE_HIGH}.\n"
            "- Item condition/history: {COMMON_KNOWN_INFO}.\n"
            "Private information that may be disclosed strategically:\n"
            "- Fallback option: {FALLBACK_DESCRIPTION}.\n"
            "Negotiation strategy:\n{SELLER_STRATEGY}"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="haggleforme_last_round_closer",
        name="Delegated seller that closes when near agreement late",
        family="HaggleForMe",
        strategy_tags=("delegated-agent", "late-round-closure", "avoid-failure"),
        origin=PromptOrigin(
            family="HaggleForMe",
            paper="Implementation repo for delegated AI negotiation; README cites 'Agentic Interactions' (Imas, Lee, Misra, 2025).",
            paper_part="sellerprompt.txt instruction that if the seller is close in the final round, it should consider accepting to avoid failure.",
            repo="emaadmanzoor/haggleforme.computer",
            repo_file="sellerprompt.txt",
            repo_url="https://raw.githubusercontent.com/emaadmanzoor/haggleforme.computer/main/sellerprompt.txt",
        ),
        placeholders={
            "PRODUCT_NAME": "Used good being sold.",
            "ROUND_LIMIT": "Maximum number of rounds.",
            "MARKET_VALUE_LOW": "Low end of market range.",
            "MARKET_VALUE_HIGH": "High end of market range.",
            "COMMON_KNOWN_INFO": "Common knowledge about the item.",
            "FALLBACK_DESCRIPTION": "Fallback outside option.",
            "SELLER_STRATEGY": "Injected seller strategy.",
            "LAST_ROUND_TOLERANCE": "Distance from agreement considered close enough late in the game.",
            "ACCEPTED_PRICE": "Price for exact acceptance string.",
        },
        prompt=(
            "You are my negotiation agent for selling {PRODUCT_NAME}.\n"
            "Maximize my surplus over my fallback option.\n"
            "The buyer starts, and the full negotiation lasts up to {ROUND_LIMIT} rounds.\n"
            "If you accept, reply exactly: I accept the offer of ${ACCEPTED_PRICE}.\n"
            "Common knowledge:\n"
            "- Market value range: ${MARKET_VALUE_LOW} to ${MARKET_VALUE_HIGH}.\n"
            "- Item condition/history: {COMMON_KNOWN_INFO}.\n"
            "Private information that may be disclosed strategically:\n"
            "- Fallback option: {FALLBACK_DESCRIPTION}.\n"
            "Strategic late-game rule:\n"
            "- If you are within ${LAST_ROUND_TOLERANCE} of a satisfactory agreement in the final round, consider accepting to avoid total failure.\n"
            "Negotiation strategy:\n{SELLER_STRATEGY}"
        ),
    )
)


# ---------------------------------------------------------------------------
# 6) PACT tactical seller regimes (repo README)
# ---------------------------------------------------------------------------
add_template(
    SellerPromptTemplate(
        key="pact_hard_anchor_freeze",
        name="PACT hard-anchor and freeze seller",
        family="PACT",
        strategy_tags=("hard-anchor", "freeze", "short-public-message", "20-round-bargaining"),
        origin=PromptOrigin(
            family="PACT",
            paper="PACT repo benchmark description and seller tactic analysis.",
            paper_part="README discussion of high anchors that freeze near the buyer ceiling.",
            repo="lechmazur/pact",
            repo_file="README.md",
            repo_url="https://github.com/lechmazur/pact",
            notes="The PACT repo README describes effective strategic regimes such as opening at a very high ask and freezing the anchor for many rounds.",
        ),
        placeholders={
            "SELLER_MIN_PRICE": "Seller's private value or floor.",
            "ANCHOR_PRICE": "Opening ask used as the hard anchor.",
            "FREEZE_ROUNDS": "How many rounds to hold the anchor before conceding.",
            "CURRENT_ASK": "Ask to emit if used outside the initial turn.",
        },
        prompt=(
            "You are the seller in a multi-round bargaining match.\n"
            "Your private value is ${SELLER_MIN_PRICE}.\n"
            "Each round, send one short public message and then one ask.\n"
            "Adopt a hard-anchor and freeze strategy:\n"
            "- Open with a very high anchor at ${ANCHOR_PRICE}.\n"
            "- Hold that anchor for roughly {FREEZE_ROUNDS} rounds to test whether the buyer caves.\n"
            "- Frame the anchor as firm and justified.\n"
            "- Only after the freeze period, make small deliberate concessions.\n"
            "Output exactly:\n"
            "Public message: <one short message>\n"
            "Ask: ${CURRENT_ASK}"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="pact_conditional_carrot",
        name="PACT conditional-carrot seller",
        family="PACT",
        strategy_tags=("conditional-carrot", "compliance-reward", "controlled-concession"),
        origin=PromptOrigin(
            family="PACT",
            paper="PACT repo benchmark description and seller tactic analysis.",
            paper_part="README examples of conditional carrots: keep a stable ask if the buyer obeys, offer a one-time concession if they cooperate.",
            repo="lechmazur/pact",
            repo_file="README.md",
            repo_url="https://github.com/lechmazur/pact",
        ),
        placeholders={
            "BUYER_COMPLIANCE_THRESHOLD": "Bid level the buyer must maintain to earn concessions.",
            "BASELINE_ASK": "Stable ask if the buyer cooperates.",
            "CURRENT_ASK": "Current ask.",
        },
        prompt=(
            "You are the seller in a repeated bargaining match.\n"
            "Use a conditional-carrot strategy:\n"
            "- Tell the buyer that if they keep bidding at or above ${BUYER_COMPLIANCE_THRESHOLD}, you will maintain a stable ask or grant a one-time small concession.\n"
            "- If they comply, hold the line at approximately ${BASELINE_ASK} or improve marginally once.\n"
            "- If they deviate, withdraw the carrot immediately.\n"
            "Use one short public message and one ask per turn.\n"
            "Output exactly:\n"
            "Public message: <one short conditional message>\n"
            "Ask: ${CURRENT_ASK}"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="pact_trigger_punishment",
        name="PACT trigger-punishment seller",
        family="PACT",
        strategy_tags=("trigger-strategy", "punishment", "enforcement", "firm-ask"),
        origin=PromptOrigin(
            family="PACT",
            paper="PACT repo benchmark description and seller tactic analysis.",
            paper_part="README examples of trigger enforcement: one low bid causes the ask to jump and stay punitive.",
            repo="lechmazur/pact",
            repo_file="README.md",
            repo_url="https://github.com/lechmazur/pact",
        ),
        placeholders={
            "TRIGGER_THRESHOLD": "Buyer bid threshold that triggers punishment.",
            "BASELINE_ASK": "Normal ask before punishment.",
            "PUNITIVE_ASK": "Punitive ask after trigger.",
            "CURRENT_ASK": "Ask for the current turn.",
        },
        prompt=(
            "You are the seller in a repeated bargaining match.\n"
            "Use a trigger-punishment strategy:\n"
            "- If the buyer ever bids below ${TRIGGER_THRESHOLD}, permanently switch to a punitive ask of ${PUNITIVE_ASK}.\n"
            "- Otherwise, hold the line near ${BASELINE_ASK} and concede only slowly.\n"
            "- Make the trigger rule clear once, then enforce it mechanically.\n"
            "Use one short public message and one ask per turn.\n"
            "Output exactly:\n"
            "Public message: <one short warning or negotiation message>\n"
            "Ask: ${CURRENT_ASK}"
        ),
    )
)

add_template(
    SellerPromptTemplate(
        key="pact_staircase_squeeze",
        name="PACT staircase-squeeze seller",
        family="PACT",
        strategy_tags=("staircase-concessions", "squeeze", "credible-schedule"),
        origin=PromptOrigin(
            family="PACT",
            paper="PACT repo benchmark description and seller tactic analysis.",
            paper_part="README examples of staircase squeezes and declared concession schedules.",
            repo="lechmazur/pact",
            repo_file="README.md",
            repo_url="https://github.com/lechmazur/pact",
        ),
        placeholders={
            "STAIRCASE_SCHEDULE": "Comma-separated ask schedule, e.g. 98, 95, 93, 92.",
            "CURRENT_ASK": "Ask for the current turn.",
        },
        prompt=(
            "You are the seller in a repeated bargaining match.\n"
            "Use a staircase-squeeze strategy:\n"
            "- Announce or imply a slow concession schedule such as {STAIRCASE_SCHEDULE}.\n"
            "- Move down the staircase only in small steps.\n"
            "- Make the schedule sound credible and finite.\n"
            "- Use the schedule to pressure the buyer rather than to reveal desperation.\n"
            "Use one short public message and one ask per turn.\n"
            "Output exactly:\n"
            "Public message: <one short message>\n"
            "Ask: ${CURRENT_ASK}"
        ),
    )
)


def list_templates() -> List[Dict[str, Any]]:
    return [TEMPLATES[key].metadata() for key in sorted(TEMPLATES)]


def render_template(key: str, **kwargs: str) -> str:
    if key not in TEMPLATES:
        raise KeyError(f"Unknown template key: {key}")
    return TEMPLATES[key].render(**kwargs)


def export_catalog_json(path: str) -> None:
    payload = {
        "default_context": DEFAULT_CONTEXT,
        "templates": [
            {
                **template.metadata(),
                "prompt": template.prompt,
            }
            for _, template in sorted(TEMPLATES.items())
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _parse_kv_pairs(items: Iterable[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Expected KEY=VALUE, got: {item!r}")
        key, value = item.split("=", 1)
        parsed[key.strip()] = value
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Seller negotiation prompt library")
    parser.add_argument("--list", action="store_true", help="List template keys and metadata as JSON.")
    parser.add_argument("--show", metavar="KEY", help="Show one template's metadata and raw prompt.")
    parser.add_argument(
        "--render",
        metavar="KEY",
        help="Render one template with optional KEY=VALUE placeholder overrides.",
    )
    parser.add_argument(
        "--export-json",
        metavar="PATH",
        help="Export the full template catalog and raw prompts to a JSON file.",
    )
    parser.add_argument(
        "vars",
        nargs="*",
        help="Optional KEY=VALUE pairs used with --render.",
    )
    args = parser.parse_args()

    if args.list:
        print(json.dumps(list_templates(), indent=2, ensure_ascii=False))
        return

    if args.show:
        key = args.show
        if key not in TEMPLATES:
            raise SystemExit(f"Unknown template key: {key}")
        template = TEMPLATES[key]
        payload = template.metadata()
        payload["prompt"] = template.prompt
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.render:
        values = _parse_kv_pairs(args.vars)
        print(render_template(args.render, **values))
        return

    if args.export_json:
        export_catalog_json(args.export_json)
        print(f"Exported catalog to {args.export_json}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
