import json
import datetime
from pathlib import Path
 
from openai import OpenAI
 
from NegoLib.Entities.Agents     import BUDGET_MERCHANT, LOCAL_SUPPLIER
from NegoLib.Entities.scenarios  import KIOSK_COLA, OFFICE_LOBBY
from NegoLib.Entities.utility    import merchant_utility, supplier_utility
from NegoLib.prompt_ensemble import (
    build_merchant_prompt,
    build_supplier_prompt,
    build_judge_prompt,
    Agent_call,
    Judge_call,
)
 
def _serialize_agent(agent):
    """Convert an Agent dataclass to a plain dict."""
    return {
        "id":          agent.id,
        "name":        agent.name,
        "description": agent.description,
        "internal_costs": {
            "beverage":    agent.internal_costs.beverage,
            "snack":       agent.internal_costs.snack,
            "convenience": agent.internal_costs.convenience,
        },
        "max_rounds":  agent.max_rounds,
    }
 
 
def _serialize_scenario(scenario):
    """Convert a Scenario dataclass to a plain dict."""
    return {
        "id":          scenario.id,
        "name":        scenario.name,
        "location":    scenario.location,
        "description": scenario.description,
        "orders": [
            {
                "product_name":    o.product.name,
                "category":        o.product.category,
                "production_cost": o.product.cost,
                "market_price":    o.product.market_price,
                "min_units":       o.min_units,
            }
            for o in scenario.orders
        ],
        "total_min_units":        scenario.total_min_units,
        "merchant_budget_floor":  round(scenario.merchant_budget_floor, 4),
        "merchant_revenue_ceiling": round(scenario.merchant_revenue_ceiling, 4),
    }
 

def simple_exp_run(
        client,
        MODEL,
        scenario,
        merchant,
        supplier,
        merchant_strategy,
        supplier_strategy,
        verbose = True
):
    STRATEGY_M = merchant_strategy
    STRATEGY_S = supplier_strategy
    MAX_ROUNDS = min(merchant.max_rounds, supplier.max_rounds)


    if verbose:
        print('=' * 70)

        print(f'Scenario : {scenario.name}')
        print(f'Merchant : {merchant.name}  |  Strategy: {STRATEGY_M}')
        print(f'Supplier : {supplier.name}  |  Strategy: {STRATEGY_S}')
        print('=' * 70)

    history     = []
    deal_closed = False
    rounds_log  = []      # per-round structured records
    judge_system = build_judge_prompt(scenario)

    for round_num in range(1, MAX_ROUNDS + 1):
        if verbose:
            print(f'\n--- Round {round_num} ---')

        round_record = {"round": round_num}

        # ---- Merchant turn ----
        m_system = build_merchant_prompt(
            merchant=merchant, scenario=scenario,
            strategy=STRATEGY_M, utility=merchant_utility,
            current_round=round_num,
        )
        m_answer, m_reasoning = Agent_call(
            client, MODEL, m_system, history, opening=(round_num == 1)
        )
        history.append({'speaker': 'MERCHANT', 'content': m_answer})
        if verbose:
            print(f'[MERCHANT]: {m_answer}\n')

        round_record["merchant"] = {
            "answer":    m_answer,
            "reasoning": m_reasoning,
            "system_prompt": m_system,
        }

        # ---- Supplier turn ----
        s_system = build_supplier_prompt(
            supplier=supplier, scenario=scenario,
            strategy=STRATEGY_S, utility=supplier_utility,
            current_round=round_num,
        )
        s_answer, s_reasoning = Agent_call(
            client, MODEL, s_system, history
        )
        history.append({'speaker': 'SUPPLIER', 'content': s_answer})

        if verbose:
            print(f'[SUPPLIER]: {s_answer}\n')

        round_record["supplier"] = {
            "answer":    s_answer,
            "reasoning": s_reasoning,
            "system_prompt": s_system,
        }

        # ---- Judge turn ----
        j_answer, j_reasoning = Judge_call(client, MODEL, judge_system, history)
        if verbose:
            print(f'[JUDGE]:\n{j_answer}\n')

        round_record["judge"] = {
            "answer":    j_answer,
            "reasoning": j_reasoning,
            "system_prompt": judge_system,
        }

        rounds_log.append(round_record)

        if 'DEAL_CLOSED' in j_answer:
            deal_closed = True
            break

    outcome = "DEAL_CLOSED" if deal_closed else "NO_DEAL"
    if verbose:
        if deal_closed:
            print(f'>> DEAL CLOSED')
        else:
            print(f'>> NO DEAL — round limit reached')
        print()

    # Assemble the run record
    run_record = {
        "scenario":    _serialize_scenario(scenario),
        "merchant":  _serialize_agent(merchant),
        "supplier":  _serialize_agent(supplier),
        "strategy_merchant": STRATEGY_M,
        "strategy_supplier": STRATEGY_S,
        "outcome":     outcome,
        "total_rounds": len(rounds_log),
        "history":     list(history),   # the raw speaker/content list
        "rounds":      rounds_log,
    }
    return run_record
    
def batch_simple_exp(
    client,
    MODEL,
    N_EXPS,
    Scenarios,
    Merchants,
    Suppliers,
    Merchant_strategies,
    Supplier_strategies,
    verbose = True
):
    experiment = {
        "metadata": {
            "timestamp": datetime.datetime.now().isoformat(),
            "model":     MODEL,
        },
        "runs": []
    }
    for i in range(N_EXPS):
        scenario = Scenarios[i % len(Scenarios)]
        merchant = Merchants[i % len(Merchants)]
        supplier = Suppliers[i % len(Suppliers)]
        m_strategy = Merchant_strategies[i % len(Merchant_strategies)]
        s_strategy = Supplier_strategies[i % len(Supplier_strategies)]

        run_record = simple_exp_run(
            client, MODEL, scenario, merchant, supplier,
            m_strategy, s_strategy, verbose
        )
        experiment["runs"].append(run_record)

    return experiment


def quick_save(dic, save_path = None):
    if save_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = Path(f"quick_save_{ts}.json")
    else:
        save_path = Path(save_path)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(dic, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {save_path}")

 