import { useState, useRef, useEffect } from "react";

// ─── Icons ───────────────────────────────────────────────────────────────────
const ChevronDown = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
);
const ChevronRight = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
);
const UploadIcon = ({ size = 32 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
);
const XIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
);

// ─── Avatars ─────────────────────────────────────────────────────────────────
const MerchantAvatar = ({ size = 34 }) => (
  <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
    <rect width="40" height="40" rx="10" fill="#DBEAFE"/>
    <rect x="10" y="18" width="20" height="14" rx="2" stroke="#3B7DDD" strokeWidth="1.8" fill="#EFF6FF"/>
    <path d="M10 22h20" stroke="#3B7DDD" strokeWidth="1.2"/>
    <path d="M15 22v10M20 22v10M25 22v10" stroke="#3B7DDD" strokeWidth="1" opacity=".4"/>
    <path d="M8 18l12-8 12 8" stroke="#3B7DDD" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
  </svg>
);
const SupplierAvatar = ({ size = 34 }) => (
  <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
    <rect width="40" height="40" rx="10" fill="#FEF3C7"/>
    <rect x="9" y="14" width="16" height="16" rx="2" stroke="#B97E0A" strokeWidth="1.8" fill="#FFFBEB"/>
    <path d="M12 20h10M12 24h7" stroke="#B97E0A" strokeWidth="1.2" strokeLinecap="round" opacity=".5"/>
    <path d="M25 18l6 3v8l-6 3-2-1.2V19.2L25 18z" stroke="#B97E0A" strokeWidth="1.5" fill="#FEF3C7" strokeLinejoin="round"/>
    <path d="M25 14v4" stroke="#B97E0A" strokeWidth="1.5" strokeLinecap="round"/>
    <circle cx="25" cy="12" r="1.5" fill="#B97E0A"/>
  </svg>
);
const JudgeAvatar = ({ size = 28 }) => (
  <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
    <rect width="40" height="40" rx="10" fill="#EDE9FE"/>
    <circle cx="20" cy="16" r="6" stroke="#7C3AED" strokeWidth="1.8" fill="#F5F3FF"/>
    <path d="M14 16h12" stroke="#7C3AED" strokeWidth="1.2"/>
    <rect x="18" y="22" width="4" height="6" rx="1" stroke="#7C3AED" strokeWidth="1.5" fill="#F5F3FF"/>
    <rect x="13" y="28" width="14" height="3" rx="1.5" stroke="#7C3AED" strokeWidth="1.5" fill="#EDE9FE"/>
  </svg>
);

// ─── Theme (Claude.ai–inspired warm neutrals) ───────────────────────────────
const T = {
  bg: "#EEECE8",
  surface: "#FAF9F7",
  surfaceHover: "#F1EFEC",
  surfaceActive: "#E8E5E0",
  border: "#DBD8D2",
  borderLight: "#E8E5E0",
  text: "#1B1B18",
  textSecondary: "#5D5D5A",
  textTertiary: "#9B9B97",
  merchant: "#2563EB",
  merchantBorder: "#BFDBFE",
  merchantBubble: "#EFF6FF",
  supplier: "#B45309",
  supplierBorder: "#FDE68A",
  supplierBubble: "#FFFBEB",
  judge: "#7C3AED",
  judgeBg: "#F5F3FF",
  judgeBorder: "#DDD6FE",
  accent: "#6D5CE7",
  accentLight: "#EDE9FE",
  success: "#16A34A",
  successBg: "#DCFCE7",
  danger: "#DC2626",
  dangerBg: "#FEE2E2",
  radius: "12px",
  radiusSm: "8px",
  font: "'Tiempos Text', 'Georgia', 'Times New Roman', ui-serif, serif",
  sans: "-apple-system, 'Segoe UI', 'Helvetica Neue', sans-serif",
  mono: "'SF Mono', 'Fira Code', 'Consolas', monospace",
};

// ─── Popover ─────────────────────────────────────────────────────────────────

function InfoPopover({ label, children, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div ref={ref} style={{
      position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 100,
      background: T.surface, border: `1px solid ${T.border}`,
      borderRadius: T.radius, padding: "18px 20px", minWidth: 320, maxWidth: 460,
      boxShadow: "0 8px 30px rgba(0,0,0,.08), 0 1px 3px rgba(0,0,0,.05)",
      animation: "popIn .12s ease",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.textTertiary, textTransform: "uppercase", letterSpacing: ".08em", fontFamily: T.sans }}>{label}</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: T.textTertiary, cursor: "pointer", padding: 2, lineHeight: 0 }}><XIcon /></button>
      </div>
      {children}
    </div>
  );
}

function PillButton({ onClick, active, color, children }) {
  return (
    <button onClick={onClick} style={{
      background: active ? `${color}12` : "transparent",
      border: `1px solid ${active ? color + "35" : T.border}`,
      borderRadius: 20, padding: "6px 15px",
      display: "inline-flex", alignItems: "center", gap: 7,
      cursor: "pointer", color: active ? color : T.textSecondary,
      fontSize: 14, fontFamily: T.sans, fontWeight: 500,
      transition: "all .15s ease", lineHeight: 1,
    }}>
      {children}
    </button>
  );
}

// ─── Badges ──────────────────────────────────────────────────────────────────

function AgentBadge({ agent, role }) {
  const [open, setOpen] = useState(false);
  const color = role === "merchant" ? T.merchant : T.supplier;
  const Av = role === "merchant" ? MerchantAvatar : SupplierAvatar;
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <PillButton onClick={() => setOpen(!open)} active={open} color={color}>
        <Av size={20} /> {agent.name}
      </PillButton>
      {open && (
        <InfoPopover label={`${role} · ${agent.id}`} onClose={() => setOpen(false)}>
          <div style={{ fontSize: 14, color: T.text, lineHeight: 1.7 }}>
            <p style={{ color: T.textSecondary, fontSize: 14, marginBottom: 14 }}>{agent.description}</p>
            <div style={{ padding: "12px 14px", background: T.bg, borderRadius: T.radiusSm, fontFamily: T.mono, fontSize: 13, lineHeight: 2, marginBottom: 12 }}>
              <span style={{ color: T.textTertiary }}>Beverage</span> ${agent.internal_costs.beverage.toFixed(2)}
              &nbsp;&nbsp;<span style={{ color: T.textTertiary }}>Snack</span> ${agent.internal_costs.snack.toFixed(2)}
              &nbsp;&nbsp;<span style={{ color: T.textTertiary }}>Conv.</span> ${agent.internal_costs.convenience.toFixed(2)}
            </div>
            <div style={{ fontSize: 14, color: T.textSecondary }}>Max rounds: <strong style={{ color: T.text }}>{agent.max_rounds}</strong></div>
          </div>
        </InfoPopover>
      )}
    </div>
  );
}

function ScenarioBadge({ scenario }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <PillButton onClick={() => setOpen(!open)} active={open} color={T.accent}>
        {scenario.name}
      </PillButton>
      {open && (
        <InfoPopover label={`Scenario · ${scenario.id}`} onClose={() => setOpen(false)}>
          <div style={{ fontSize: 14, color: T.text, lineHeight: 1.7 }}>
            <div style={{ fontSize: 13, color: T.textSecondary, marginBottom: 4, fontFamily: T.sans }}>{scenario.location}</div>
            <p style={{ color: T.textSecondary, fontSize: 14, marginBottom: 14 }}>{scenario.description}</p>
            <table style={{ fontSize: 13, fontFamily: T.mono, borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr style={{ color: T.textTertiary, fontSize: 11.5 }}>
                  <th style={{ textAlign: "left", padding: "6px 8px", borderBottom: `1px solid ${T.border}`, fontWeight: 500, fontFamily: T.sans }}>Product</th>
                  <th style={{ textAlign: "right", padding: "6px 8px", borderBottom: `1px solid ${T.border}`, fontWeight: 500, fontFamily: T.sans }}>Cost</th>
                  <th style={{ textAlign: "right", padding: "6px 8px", borderBottom: `1px solid ${T.border}`, fontWeight: 500, fontFamily: T.sans }}>Price</th>
                  <th style={{ textAlign: "right", padding: "6px 8px", borderBottom: `1px solid ${T.border}`, fontWeight: 500, fontFamily: T.sans }}>Qty</th>
                </tr>
              </thead>
              <tbody>
                {scenario.orders.map((o, i) => (
                  <tr key={i}>
                    <td style={{ padding: "5px 8px", color: T.text, fontFamily: T.sans, fontSize: 13 }}>{o.product_name}</td>
                    <td style={{ padding: "5px 8px", textAlign: "right", color: T.textTertiary }}>${o.production_cost.toFixed(2)}</td>
                    <td style={{ padding: "5px 8px", textAlign: "right", color: T.text }}>${o.market_price.toFixed(2)}</td>
                    <td style={{ padding: "5px 8px", textAlign: "right", color: T.textSecondary }}>{o.min_units}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </InfoPopover>
      )}
    </div>
  );
}

// ─── Reasoning Toggle ────────────────────────────────────────────────────────

function ReasoningToggle({ reasoning }) {
  const [open, setOpen] = useState(false);
  if (!reasoning) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <button onClick={() => setOpen(!open)} style={{
        background: "none", border: "none", color: T.textTertiary, cursor: "pointer",
        fontSize: 13, fontFamily: T.sans, display: "inline-flex", alignItems: "center", gap: 4,
        padding: 0, transition: "color .15s", fontWeight: 500,
      }}
        onMouseEnter={e => e.currentTarget.style.color = T.textSecondary}
        onMouseLeave={e => e.currentTarget.style.color = T.textTertiary}
      >
        {open ? <ChevronDown /> : <ChevronRight />}
        {open ? "Hide reasoning" : "Show reasoning"}
      </button>
      {open && (
        <div style={{
          marginTop: 8, padding: "12px 14px", fontSize: 13, lineHeight: 1.7,
          color: T.textSecondary, background: T.bg, borderRadius: T.radiusSm,
          borderLeft: `2.5px solid ${T.border}`, fontFamily: T.mono,
          whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflowY: "auto",
        }}>
          {reasoning}
        </div>
      )}
    </div>
  );
}

// ─── Chat Messages ───────────────────────────────────────────────────────────

function MerchantMessage({ content, reasoning }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginBottom: 14, paddingLeft: "12%" }}>
      <div style={{ maxWidth: "70%" }}>
        <div style={{ fontSize: 12, color: T.merchant, fontWeight: 600, textAlign: "right", marginBottom: 5, letterSpacing: ".03em", fontFamily: T.sans }}>MERCHANT</div>
        <div style={{
          padding: "14px 18px", borderRadius: "18px 18px 4px 18px",
          background: T.merchantBubble, border: `1px solid ${T.merchantBorder}`,
          fontSize: 15, lineHeight: 1.7, color: T.text,
          whiteSpace: "pre-wrap", wordBreak: "break-word", textAlign: "left",
        }}>
          {content}
          <ReasoningToggle reasoning={reasoning} />
        </div>
      </div>
      <div style={{ flexShrink: 0, marginTop: 24 }}><MerchantAvatar size={36} /></div>
    </div>
  );
}

function SupplierMessage({ content, reasoning }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-start", gap: 12, marginBottom: 14, paddingRight: "12%" }}>
      <div style={{ flexShrink: 0, marginTop: 24 }}><SupplierAvatar size={36} /></div>
      <div style={{ maxWidth: "70%" }}>
        <div style={{ fontSize: 12, color: T.supplier, fontWeight: 600, marginBottom: 5, letterSpacing: ".03em", fontFamily: T.sans }}>SUPPLIER</div>
        <div style={{
          padding: "14px 18px", borderRadius: "18px 18px 18px 4px",
          background: T.supplierBubble, border: `1px solid ${T.supplierBorder}`,
          fontSize: 15, lineHeight: 1.7, color: T.text,
          whiteSpace: "pre-wrap", wordBreak: "break-word", textAlign: "left",
        }}>
          {content}
          <ReasoningToggle reasoning={reasoning} />
        </div>
      </div>
    </div>
  );
}

function JudgeMessage({ content, reasoning }) {
  return (
    <div style={{ display: "flex", justifyContent: "center", marginBottom: 14, padding: "0 8%" }}>
      <div style={{ maxWidth: "65%", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, justifyContent: "center", marginBottom: 5 }}>
          <JudgeAvatar size={22} />
          <span style={{ fontSize: 12, color: T.judge, fontWeight: 600, letterSpacing: ".03em", fontFamily: T.sans }}>JUDGE</span>
        </div>
        <div style={{
          padding: "14px 18px", borderRadius: T.radius,
          background: T.judgeBg, border: `1px solid ${T.judgeBorder}`,
          fontSize: 14, lineHeight: 1.7, color: T.textSecondary,
          whiteSpace: "pre-wrap", wordBreak: "break-word", textAlign: "left",
        }}>
          {content}
          <ReasoningToggle reasoning={reasoning} />
        </div>
      </div>
    </div>
  );
}

// ─── Conversation View ───────────────────────────────────────────────────────

function ConversationView({ run }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{
        padding: "13px 22px", borderBottom: `1px solid ${T.border}`,
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9, flexShrink: 0,
        background: T.surface,
      }}>
        <ScenarioBadge scenario={run.scenario} />
        <AgentBadge agent={run.merchant} role="merchant" />
        <span style={{ color: T.textTertiary, fontSize: 13, fontWeight: 500, fontFamily: T.sans }}>vs</span>
        <AgentBadge agent={run.supplier} role="supplier" />
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 13, fontFamily: T.mono, color: T.textTertiary }}>
            {run.strategy_merchant} / {run.strategy_supplier}
          </span>
          <span style={{
            fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 20,
            background: run.outcome === "DEAL_CLOSED" ? T.successBg : T.dangerBg,
            color: run.outcome === "DEAL_CLOSED" ? T.success : T.danger,
            fontFamily: T.sans,
          }}>
            {run.outcome === "DEAL_CLOSED" ? "Deal Closed" : "No Deal"}
          </span>
          <span style={{ fontSize: 12, color: T.textTertiary, fontFamily: T.mono }}>{run.total_rounds}R</span>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "18px 28px", background: T.bg }}>
        {run.rounds.map((rr, ri) => (
          <div key={ri}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "24px 0 18px" }}>
              <div style={{ height: 1, flex: 1, background: T.border }} />
              <span style={{
                fontSize: 11.5, fontWeight: 600, color: T.textTertiary,
                letterSpacing: ".1em", textTransform: "uppercase",
                padding: "4px 16px", background: T.surface, borderRadius: 20,
                border: `1px solid ${T.border}`, fontFamily: T.sans,
              }}>
                Round {rr.round}
              </span>
              <div style={{ height: 1, flex: 1, background: T.border }} />
            </div>
            <MerchantMessage content={rr.merchant.answer} reasoning={rr.merchant.reasoning} />
            <SupplierMessage content={rr.supplier.answer} reasoning={rr.supplier.reasoning} />
            <JudgeMessage content={rr.judge.answer} reasoning={rr.judge.reasoning} />
          </div>
        ))}
        <div style={{ height: 28 }} />
      </div>
    </div>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

function RunListItem({ run, index, selected, onClick }) {
  const isActive = selected === index;
  return (
    <button onClick={() => onClick(index)} style={{
      width: "100%", textAlign: "left",
      background: isActive ? T.surfaceActive : "transparent",
      border: "none",
      borderLeft: `3px solid ${isActive ? T.accent : "transparent"}`,
      padding: "14px 18px", cursor: "pointer", fontFamily: T.sans,
      transition: "background .1s", borderBottom: `1px solid ${T.borderLight}`,
    }}
      onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = T.surfaceHover; }}
      onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = isActive ? T.surfaceActive : "transparent"; }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 14, fontWeight: isActive ? 600 : 500, color: T.text }}>{run.scenario.name}</span>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 10,
          background: run.outcome === "DEAL_CLOSED" ? T.successBg : T.dangerBg,
          color: run.outcome === "DEAL_CLOSED" ? T.success : T.danger,
        }}>
          {run.outcome === "DEAL_CLOSED" ? "Deal" : "No deal"}
        </span>
      </div>
      <div style={{ fontSize: 12.5, color: T.textTertiary, display: "flex", gap: 6 }}>
        <span>{run.merchant.id} vs {run.supplier.id}</span>
        <span style={{ opacity: .35 }}>·</span>
        <span>{run.total_rounds}R</span>
        <span style={{ opacity: .35 }}>·</span>
        <span>{run.strategy_merchant} / {run.strategy_supplier}</span>
      </div>
    </button>
  );
}

// ─── Upload ──────────────────────────────────────────────────────────────────

function UploadScreen({ onLoad }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleFile = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        if (data.runs && Array.isArray(data.runs)) onLoad(data);
        else alert("Invalid format: expected { runs: [...] }");
      } catch { alert("Failed to parse JSON."); }
    };
    reader.readAsText(file);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 28 }}>
      <div style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: 26, fontWeight: 700, color: T.text, marginBottom: 6, fontFamily: T.font }}>NegoLib Viewer</h1>
        <p style={{ fontSize: 16, color: T.textTertiary, fontFamily: T.sans }}>Upload an experiment JSON to explore negotiations</p>
      </div>
      <div
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => inputRef.current?.click()}
        style={{
          width: 400, padding: "48px 40px", borderRadius: 16, textAlign: "center",
          border: `2px dashed ${dragOver ? T.accent : T.border}`,
          background: dragOver ? T.accentLight : T.surface, cursor: "pointer",
          transition: "all .2s",
          boxShadow: "0 1px 4px rgba(0,0,0,.04)",
        }}
      >
        <div style={{ marginBottom: 16, color: dragOver ? T.accent : T.textTertiary }}><UploadIcon /></div>
        <div style={{ fontSize: 16, fontWeight: 500, color: T.text, marginBottom: 8, fontFamily: T.sans }}>Drop your JSON file here</div>
        <div style={{ fontSize: 14, color: T.textTertiary, marginBottom: 20, fontFamily: T.sans }}>or click to browse</div>
        <div style={{
          display: "inline-block", padding: "10px 24px", borderRadius: 8,
          background: T.accent, color: "#fff", fontSize: 14, fontWeight: 600, fontFamily: T.sans,
        }}>
          Choose file
        </div>
        <input ref={inputRef} type="file" accept=".json" style={{ display: "none" }}
          onChange={e => handleFile(e.target.files[0])} />
      </div>
    </div>
  );
}

// ─── App ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(0);

  const css = `
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { overflow: hidden; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: ${T.border}; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: ${T.textTertiary}; }
    @keyframes popIn {
      from { opacity: 0; transform: translateY(-4px) scale(.98); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
  `;

  if (!data) {
    return (
      <div style={{ height: "100vh", background: T.bg, fontFamily: T.sans }}>
        <style>{css}</style>
        <UploadScreen onLoad={(d) => { setData(d); setSelected(0); }} />
      </div>
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", fontFamily: T.font, background: T.bg, color: T.text }}>
      <style>{css}</style>

      <div style={{
        width: 300, minWidth: 300, borderRight: `1px solid ${T.border}`,
        display: "flex", flexDirection: "column", background: T.surface,
      }}>
        <div style={{
          padding: "16px 20px", borderBottom: `1px solid ${T.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-.02em", color: T.text }}>NegoLib</div>
            <div style={{ fontSize: 12.5, color: T.textTertiary, marginTop: 2, fontFamily: T.sans }}>
              {data.runs.length} run{data.runs.length !== 1 ? "s" : ""} · {data.metadata?.model || "—"}
            </div>
          </div>
          <button onClick={() => { setData(null); setSelected(0); }} style={{
            background: T.bg, border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
            color: T.textSecondary, cursor: "pointer", padding: "5px 12px", fontSize: 12.5,
            fontFamily: T.sans, fontWeight: 500,
          }}>
            New file
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {data.runs.map((run, i) => (
            <RunListItem key={i} run={run} index={i} selected={selected} onClick={setSelected} />
          ))}
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {data.runs[selected] ? (
          <ConversationView run={data.runs[selected]} />
        ) : (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: T.textTertiary, fontSize: 16 }}>
            Select a run
          </div>
        )}
      </div>
    </div>
  );
}