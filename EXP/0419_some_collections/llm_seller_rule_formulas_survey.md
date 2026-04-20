
# Seller-side negotiation rule formulas in current LLM bargaining literature

## Scope

This note normalizes the seller-side negotiation behavior from recent LLM bargaining papers and public codebases into a common scalar-price notation.

### Notation

- \(S_t\): seller's next proposed price at turn \(t\)
- \(B_t\): buyer's latest offer before the seller acts at turn \(t\)
- \(M\): market / retail / list / reference price (I normalize all of these to \(M\))
- \(v\): seller's private internal cost / wholesale price / fallback floor
- \(t\): turn index; \(T\) denotes the maximum number of turns if the source has one
- \(B_t^+ = \max_{k \le t} B_k\): highest buyer offer seen so far
- \(\Delta B_t = B_t - B_{t-1}\): buyer concession between the last two buyer offers
- \(g_t = S_{t-1} - B_t\): current buyer-seller gap
- \(\widehat W_t\): a seller-side estimate of the buyer's ceiling, inferred only from \((M, B_{1:t}, S_{1:t-1})\)

### Important caveat

The literature is **not** dominated by papers that publish a closed-form recurrence \(S_t = f(M,v,B_{1:t},S_{1:t-1},t)\).

What current papers usually publish is one of three things:

1. **An explicit admissibility / control rule** (for example: never sell below cost, accept only if the price is above wholesale, quit after limited turns).
2. **A semi-explicit update mechanism** (for example: a truncated-normal price sampler, a structured action space, or a worked dialogue example that clearly implies a concession pattern).
3. **A qualitative tactic or persona** (for example: patient, aggressive, warm, cooperative, deceptive, tit-for-tat), which I then normalize into a clearly labeled **hypothesized** scalar seller rule.

I keep those three cases separate below.

## What I found at a glance

- The most common seller-side rule in current product-market LLM papers is **not** an explicit concession curve. It is the **reservation-floor invariant**: keep the seller's cost / wholesale / minimum acceptable price private, and never finalize below it.
- The most explicit seller-side price generator I found in the product-seller literature is **FishBargain**: its seller agent chooses an action and language skill, then samples a counter-price from a **truncated normal distribution** whose bounds are defined from the latest buyer offer and the seller's bottom price.
- The next most common pattern is **structured but still qualitative control**: initial ask, hidden minimum price, limited turns, exact action grammar, and short natural language responses.
- The newest systems add a second layer on top of that: **opponent-awareness** (estimate the buyer's ceiling), **behavioral overlays** (patient vs impatient, warm vs dominant, deceptive vs fair), or **punishment / contract tactics** (grim triggers, standing rules, freeze).

---

## Table 1 — Direct or semi-direct seller rules actually stated in papers or code

| Strategy / rule family | Directness | Source | What the source explicitly gives | Normalized seller rule for \(S_t\) |
|---|---|---|---|---|
| **Initial asking-price anchor** | Direct | **GPT-Bargaining** repo: `lib_prompt/seller.txt`; **AgenticPay** 2026, **Table 15** | Seller is given a starting / initial asking price and told to sell high or maximize profit | **Rule:** \(S_1 = S_{\text{init}}\). In scalar form, the literature often externalizes the opening anchor rather than deriving it endogenously. |
| **Reservation floor / wholesale floor** | Direct invariant | **Xia et al. 2024**, **Table 8** (“Prompts for Seller”); repo: `SellerAgent.py`; **The Automated but Risky Game** 2025, **Appendix D.3 / Fig. 12**; **AgenticPay** 2026, **Table 15**; **MERIT** 2026 deceptive-seller prompt | Keep cost / wholesale / minimum acceptable price private; only agree when price exceeds cost / minimum acceptable price | **Rule:** seller proposals must satisfy \(S_t \ge v\); finalize only if \(B_t \ge v\). In normalized control-law form: propose any \(S_t \in [v,\infty)\), but never accept \(B_t < v\). |
| **Action-grammar seller controller** | Direct control law | **Xia et al. 2024**, **Table 8**; repo: `SellerAgent.py` | Seller action space is exactly `[SELL]`, `[REJECT]`, `[DEAL]`, `[QUIT]` with limited turns and an explicit rule that `[DEAL]` can only accept the buyer's previous `[BUY]` | **Rule:** if \(B_t \ge v\), seller may choose `DEAL`; if no acceptable outcome is likely before deadline, seller chooses `QUIT`; otherwise seller chooses `SELL` with some \(S_t \ge v\) or `REJECT`. This is a direct controller, even though the numeric concession step is not specified. |
| **Turn-bounded walk-away after non-progress** | Direct control law (non-price benchmark, translated to price) | **ASTRA** 2025, **§2.2 “Decision on Partner's Offer”** | Accept if the partner's offer is at least as good as the agent's most recent offer; walk away if partner makes no concessions for 3 turns, or twice offers below BATNA after warning | **Translated scalar rule:** if \(\Delta B_t \le 0\) for 3 consecutive buyer turns, stop conceding and/or walk away; if \(B_t < v\) repeatedly after warning, terminate. In normalized form: \(S_t = S_{t-1}\) under repeated buyer stagnation, then `WALK_AWAY` / `QUIT`. |
| **Price-sampler seller** | Direct update mechanism | **FishBargain** 2025, **§2.2–2.3**, **Tables 1–2** | Seller-side policy planner chooses an action and a language skill; if the action is price-related, the system generates a price “based on the latest buyer’s offer and seller’s bottom price” with a **truncated normal distribution** | **Rule:** \(S_t \sim \operatorname{TruncNormal}(l_t,h_t)\), where the paper states that \(l_t\) and \(h_t\) are defined from the latest buyer offer and seller bottom price. The exact closed forms for \(l_t,h_t\) are not published in the accessible paper text. |
| **Action + language-skill decoupling** | Direct control scaffold | **FishBargain** 2025, **Table 1** and **Table 2** | Price rule is separated from dialogue style: action set includes `PROPOSE`, `COUNTER`, `REJECT`, etc.; language skills include `Emphasis`, `Compare the Market`, `Create Urgency`, `Added Value`, etc. | **Rule:** choose an action \(a_t\); if \(a_t\) is price-bearing, generate \(S_t\) by the truncated-normal sampler; otherwise keep price implicit. This is direct at the action-policy level, and it is the clearest example of “strategy decoupling” for sellers. |
| **Structured confidential-minimum seller** | Direct invariant + direct output protocol | **AgenticPay** 2026, **Table 15**; repo: `agenticpay/agents/seller_agent.py` | Seller has an explicit initial ask, a confidential minimum acceptable price, one exact structured offer tag per turn, and a deal-finalization token | **Rule:** \(S_t\) is always the single price inside `### SELLER_PRICE($X) ###`; the admissible region is \(S_t \ge v\); acceptance is indicated by `MAKE_DEAL`. This is not a concession equation, but it is a direct per-turn seller pricing protocol. |
| **Slow narrowing / meet-in-the-middle seller** | Semi-direct (implied by worked example) | **AgenticPay** 2026, **Table 16** example dialogue; repo: `agenticpay/agents/seller_agent.py` | Worked seller sequence: buyer \(120 \to 130 \to 132 \to 133\), seller \(140 \to 135 \to 134 \to 133\) | **Rule (normalized from the example):** \(S_t = \max\{v,\ S_{t-1} - \eta_t(S_{t-1}-B_t)\}\) with \(0 < \eta_t < 1\), and \(\eta_t\) shrinking as the buyer-seller gap narrows. This captures the observed 140→135→134→133 pattern. |
| **Final-round “close if near agreement”** | Direct qualitative decision rule | **HaggleForMe** codebase: `sellerprompt.txt`; **negotiation-challenge** codebase: `prompts/cooperative.txt`, `prompts/aggressive.txt` | In the final round, if close to agreement, prefer acceptance to avoid failure / no-deal penalty | **Rule:** use a deadline-softened acceptance threshold: accept if \(B_t \ge v + \epsilon_t\) with \(\epsilon_t \downarrow 0\) as \(t \to T\). This rule is stated qualitatively, but the scalar form is straightforward. |
| **Standing-rule / frozen ask** | Direct observed tactic from logs | **PACT** codebase, `README.md` dossier section | Seller examples: “I will ask 100 every remaining round. Bid 100 or no trades.” | **Rule:** once the seller enters a freeze regime, \(S_t = s^\star\) for all future turns \(t \ge \tau\). This is one of the clearest explicit seller recurrences found in a current bargaining benchmark codebase. |
| **Grim-trigger punishment** | Direct observed tactic from logs | **PACT** codebase, `README.md` dossier section | Seller examples: “One bid ≤80 and I ask 99 permanently,” “Under 65 once → ask 66+ thereafter.” | **Rule:** if a buyer trigger is violated once, switch permanently to a punishment ask: \(S_t = s^{\text{punish}}\) for all future turns after the trigger event. In scalar notation: if \(\exists k < t\) with \(B_k \le \theta\), then \(S_t = s^{\text{punish}}\). |
| **Conditional carrot / obedience corridor** | Direct observed tactic from logs | **PACT** codebase, `README.md` dossier section | Seller example: “Bid 67 every round and I keep ask 67; one-time R11 at 66.” | **Rule:** if the buyer stays in a target corridor, maintain a favorable but stable ask: \(S_t = s^\star\) while \(B_t \in \mathcal C\); optionally grant a one-time small concession at a chosen round. |
| **Endgame spike / horizon exploitation** | Direct observed tactic from logs | **PACT** codebase, `README.md` dossier section | Seller example: “Often cashes an endgame spike (lifting from 49→50, 84→86/90/100) after training compliance.” | **Rule:** after buyer compliance has been established, raise the ask in the final period: \(S_T = S_{T-1} + \Delta\), \(\Delta > 0\). This is a rare but clearly stated seller-side opportunistic rule. |

### Reading Table 1 correctly

- Rows labeled **Direct** reproduce an actual seller rule, controller, or update mechanism from the source.
- Rows labeled **Semi-direct** are not written as equations in the source, but the source gives enough structure (for example, a worked dialogue) that the scalar recurrence is a very close normalization.
- In current product-bargaining papers, the most common “explicit rule” is **still the floor constraint** \(S_t \ge v\), **not** a published concession schedule.

---

## Table 2 — Implicit seller styles and my hypothesized scalar rules for \(S_t\)

These are the cases where the literature gives a **tactic label**, **persona**, or **behavioral descriptor**, but not a closed-form price update. I convert them into a plausible scalar seller policy using only the allowed ingredients \((M, v, t, B_{1:t}, S_{1:t-1})\).

| Implicit strategy / style | Source | Hypothesized scalar seller rule | Why this is the right normalized form |
|---|---|---|---|
| **High anchor / aggressive early offer** | **ASTRA** 2025, **Table 5** (`Aggressive Early Offers`); **AgreeMate** personality results; **PACT** seller dossier | \(S_1 = M + \kappa(M-v)\), \(\kappa \ge 0\); then \(S_t = v + (S_1-v)e^{-\lambda_a(t-1)}\) with fast early movement and later flattening | The sources repeatedly describe a strong opening anchor plus either “room for later concessions” or “steep price adjustments early.” An exponential front-loaded concession curve is the cleanest scalar version of that. |
| **Hold firm on value** | **AgenticPay** repo `agenticpay/agents/seller_agent.py` (“holding firm on value”); **ASTRA** 2025 `No Concession Response`, `Reject Negative Concession` | If \(\Delta B_t \le 0\), set \(S_t = S_{t-1}\); otherwise \(S_t = \max\{v,\ S_{t-1} - \alpha_h \Delta B_t\}\) with very small \(\alpha_h\) | “Holding firm” means the seller does not reward buyer stagnation. The smallest faithful scalar translation is: no buyer concession ⇒ no seller concession. |
| **Slow concession** | **AgenticPay** repo `agenticpay/agents/seller_agent.py` (“slow concession”); **Table 16** example | \(S_t = \max\{v,\ S_{t-1} - \alpha_s g_t\}\) with \(0 < \alpha_s \ll 1\) | The key idea is that the seller moves toward the buyer only slowly and only by a fraction of the current gap. |
| **Patient rational seller** | **LLMs at the Bargaining Table** 2024 seller prompt variants | \(S_t = \max\{v,\ S_{t-1} - \alpha_p g_t\}\), with \(\alpha_p\) small; accept only if \(B_t \ge S_t - \epsilon_p\) with very small \(\epsilon_p\) | The paper's seller is “strategic, aggressive, patient, and completely rational,” and is willing to keep negotiating even when a feasible deal exists. That implies a low concession rate and a strict acceptance threshold. |
| **Busy / impatient seller** | **LLMs at the Bargaining Table** 2024 seller prompt variants | \(S_t = \max\{v,\ S_{t-1} - \alpha_i g_t\}\), with \(\alpha_i > \alpha_p\); accept if \(B_t \ge S_t - \epsilon_i\), with \(\epsilon_i > \epsilon_p\) | A seller that wants to “close quickly” should converge toward the buyer faster and accept earlier. The clean scalar difference from the patient seller is a larger concession coefficient and a softer acceptance threshold. |
| **Tit-for-tat / reciprocal concession** | **ASTRA** 2025 (framework grounded in Tit-for-Tat; `Reciprocal Concessions` tactic) | \(S_t = \max\{v,\ S_{t-1} - \rho(\Delta B_t)_+\}\), and if \(\Delta B_t \le 0\), keep \(S_t = S_{t-1}\) | Tit-for-tat is most naturally translated as “match the buyer's concession rate, but do not move if the buyer does not move.” |
| **Friendly / warm / cooperative seller** | **Advancing AI Negotiations** 2025 (warmth, positivity, gratitude, question-asking associated with deals and value); **ASTRA** collaborative tactics; **negotiation-challenge** `cooperative.txt` | \(S_t = \max\{v,\ \lambda_w S_{t-1} + (1-\lambda_w)B_t\}\) with \(0.3 \le \lambda_w \le 0.6\); in the final round, accept any \(B_t > v\) | Warm / cooperative sellers try to close deals and reward reciprocity. A weighted move toward the buyer's latest offer is the cleanest scalar analogue. |
| **Fair / midpoint-seeking seller** | **AgreeMate** 2024, **§6.3.2–6.3.7** (fair/passive/aggressive personality analysis; Figures 6–12); **PACT** GLM dossier (“fairness”, “mutual benefit”, focal prices) | \(S_t = \max\left\{v,\ \frac{S_{t-1} + B_t}{2}\right\}\) | When a seller emphasizes fairness or “meeting in the middle,” the midpoint rule is the canonical scalar normalization. |
| **Passive seller** | **AgreeMate** 2024, **§6.3.2–6.3.7** (passive persona results; Figures 6, 8, 11–13) | \(S_t = \max\{v,\ S_{t-1} - \delta_p\}\), where \(\delta_p\) is a tiny constant | The paper describes passive combinations as having gradual price movements and longer negotiations. A tiny constant concession step matches that behavior. |
| **Market-comparison tether** | **FishBargain** `Compare the Market`; consumer-market systems that expose retail/list price to the seller | \(S_t = \max\{v,\ \lambda_m S_{t-1} + (1-\lambda_m)M\}\) | “Compare the Market” is naturally a tethering tactic: keep the ask close to market / retail rather than purely following the buyer's bids. |
| **Added value / guarantee / bundle offer** | **FishBargain** `Added Value`, `Transaction Guarantee`; **AgenticPay** repo (`bundle offer`) | \(S_t = \max\{v,\ \lambda_b S_{t-1} + (1-\lambda_b)B_t + \gamma\}\), with \(\gamma > 0\) | Non-price sweeteners let the seller preserve a higher nominal price than pure midpoint bargaining would allow. In scalar form, that appears as an additive premium \(\gamma\). |
| **Urgency / time pressure** | **FishBargain** `Create Urgency`; **NegotiationGym** coach prompt mentions `time-pressure` | \(S_t = S_{t-1}\) for \(t < T-\tau\); then \(S_t = \max\{v,\ S_{t-1} - \delta_u\}\) for \(t \ge T-\tau\) | Urgency usually means the seller is firm early, then introduces a controlled deadline-induced softening or a “close-now” discount near the end. |
| **Opponent-aware ceiling estimation** | **AgenticPay** repo mental-model block (`[Opponent Reservation Price]`, `[Opponent Strategy]`, `[My Strategy]`); **MERIT** 2026 `OAR` prompt | First estimate the buyer ceiling from history: \(\widehat W_t = B_t^+ + \rho_t(M-B_t^+)\), \(0 \le \rho_t \le 1\). Then set \(S_t = \max\{v,\ \widehat W_t - m_t\}\). | These sources explicitly tell the agent to reason about the opponent's hidden reservation price and flexibility. In scalar form, that means maintaining a history-based ceiling estimate and pricing just below it. |
| **Deceptive / cunning / sly seller** | **MERIT** 2026 deceptive multi-product seller prompt | \(S_t^{\text{deceptive}} = S_t^{\text{OAR}} + \mu_t\), with \(\mu_t > 0\) early and \(\mu_t \downarrow 0\) near deadline | A deceptive seller should behave like an opponent-aware seller, but with an intentionally inflated ask relative to the inferred buyer ceiling, only softening when failure risk rises. |
| **Mirroring / calibrated questioning / information extraction** | **Advancing AI Negotiations** 2025 (question-asking; Voss-style tactics); **NegotiationGym** coach prompt (`mirroring`) | Keep the ask mostly unchanged until new buyer information arrives: if \(B_t^+ = B_{t-1}^+\), set \(S_t \approx S_{t-1}\); when buyer raises the best-so-far offer, update \(S_t = \max\{v,\ \widehat W_t - m_t\}\) | These tactics are less about conceding and more about learning the buyer's ceiling. In scalar price terms, that means “concede only after information gain.” |

### Which implicit seller formulas are most faithful to the literature?

If I had to compress the implicit literature into a handful of reusable scalar seller templates, I would keep these as the most faithful:

1. **Hard floor + slow concession:**  
   \(S_t = \max\{v,\ S_{t-1} - \alpha g_t\}\), \(0 < \alpha \ll 1\)

2. **Hard floor + reciprocal concession:**  
   \(S_t = \max\{v,\ S_{t-1} - \rho(\Delta B_t)_+\}\)

3. **Hard floor + market tether:**  
   \(S_t = \max\{v,\ \lambda S_{t-1} + (1-\lambda)M\}\)

4. **Hard floor + opponent-aware pricing:**  
   \(\widehat W_t = B_t^+ + \rho_t(M-B_t^+)\), then \(S_t = \max\{v,\ \widehat W_t - m_t\}\)

5. **Hard floor + deadline softening:**  
   \(S_t = S_{t-1}\) early, then \(S_t = \max\{v,\ S_{t-1} - \delta_u\}\) near \(T\)

6. **Hard floor + trigger punishment:**  
   \(S_t = s^\star\) until a trigger event; then \(S_t = s^{\text{punish}}\) forever

That list is, in my judgment, a more faithful summary of the current LLM bargaining literature than a claim that “the literature uses one universal concession formula.”

---

## Table 3 — Across-episode prompt-learning rules (not within-dialogue \(S_t\), but common in the literature)

These are included because several papers improve negotiation not by changing the within-dialogue controller \(S_t\), but by rewriting the agent's strategy prompt across episodes.

| Meta-strategy | Source | Cross-episode rule |
|---|---|---|
| **Critic feedback / AI coach** | **Fu et al.** 2023; repo: `lib_prompt/seller_critic.txt`, `lib_prompt/seller_receive_feedback.txt` | After a dialogue, a critic suggests three generic strategies to get a higher price; the seller prompt in the next episode is updated using that feedback. |
| **Negotiation coach tactic injection** | **NegotiationGym** 2025, **Appendix Fig. 5** | After a run, a coach appends exactly one new tactic sentence (for example, anchoring, mirroring, time-pressure) to the agent's system prompt for the next run. |
| **Bandit-style prompt search** | **The Automated but Risky Game** 2025, **§5** | Prompt selection is treated as a multi-armed bandit over candidate strategy prompts; the policy is updated with a softmax-bandit rule to reduce overpayment / out-of-budget / deadlock anomalies. |
| **Utility feedback / OAR refinement** | **MERIT** 2026; **LLM Agents for Bargaining with Utility-based Feedback** 2025 | Strategy prompts are improved using structured feedback grounded in utility, negotiation power, and acquisition ratio, often with explicit opponent-aware reasoning. |

---

## What I deliberately checked but excluded from the formula tables

These sources are useful and relevant, but they do **not** publish a seller-side scalar price-update rule in a way that would justify a row in the main formula tables:

| Source | Why I excluded it from the \(S_t\)-formula tables |
|---|---|
| **FaMA** 2025 | Strong C2C marketplace assistant paper, but focused on marketplace operations and tool use rather than seller-side bargaining update rules |
| **Magentic Marketplace** 2025 | Excellent end-to-end environment for search / negotiation / transaction, but the paper emphasizes the market protocol and evaluation environment, not a seller concession formula |
| **RetailSim** 2026 | Broad retail simulation framework with seller personas and multi-turn interactions, but it does not publish a scalar seller concession rule of the form \(S_t=f(\cdot)\) |
| **Leveraging Large Language Models for Active Merchant Non-player Characters (MART)** 2024 | Merchant appraiser/negotiator framework for game NPCs, but the paper emphasizes architecture and training, not an explicit seller counteroffer recurrence |
| **Evaluating Multi-Turn Bargain Skills in LLM-Based Seller Agents** 2025 | Important seller-agent benchmark, but focused on turn-level buyer-intent tracking and evaluation rather than publishing seller counteroffer rules |

---

## Bottom line

The literature currently clusters around the following seller-rule template:

1. **Keep a hidden reservation floor \(v\)** and never violate it.
2. **Open with an externally supplied anchor** \(S_1\).
3. **Use a qualitative concession style** (slow, patient, cooperative, fair, aggressive, etc.) rather than a published closed-form update.
4. **Optionally estimate the buyer's ceiling** from the history and price just below it.
5. **Use deadline or trigger rules** to either close, freeze, punish, or spike.

So if your goal is to build a seller-side negotiator that is faithful to the literature, the most literature-consistent scalar family is not one exact \(S_t\) formula but a **family of floor-constrained update rules**:

\[
S_t = \max\left\{v,\ \Phi\!\left(M,\ B_{1:t},\ S_{1:t-1},\ t\right)\right\},
\]

where \(\Phi\) is then specialized to one of the tactic classes above:
slow concession, reciprocal concession, market tether, opponent-aware pricing, deadline softening, or trigger punishment.
