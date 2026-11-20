/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMemo, useState } from "react";
import { SECTION_LABEL } from "./schema";

const nf = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 2, minimumFractionDigits: 0 });
export const money = (v: any) => (v === null || v === undefined || v === "" ? "—" : `₪ ${nf.format(Number(v))}`);
const pctf = (v: any) => (v === null || v === undefined ? "—" : `${nf.format(Number(v))}%`);
const SEV: Record<string, string> = { critical: "קריטי", warning: "אזהרה", info: "מידע" };
const STAGE: Record<string, string> = { s62a: "62א", corporate: "חברה", s81: "81ב", individual: "מס הכנסה", nii: "ב\"ל", advances: "מקדמות" };

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Results({ result, names }: { result: any; names: Record<string, string> }) {
  const [entity, setEntity] = useState("all");
  const [showParams, setShowParams] = useState(false);
  const trace = useMemo(() => result.trace.filter((s: any) => entity === "all" || s.entity === entity), [result, entity]);
  const alerts = result.alerts.filter((a: any) => a.code !== "PARAM_UNVERIFIED");
  const unverified = result.alerts.filter((a: any) => a.code === "PARAM_UNVERIFIED");
  const entities = Array.from(new Set(result.trace.map((s: any) => s.entity))) as string[];
  const label = (e: string) => {
    const [k, id] = e.split(":");
    return `${k === "company" ? "🏢" : k === "individual" ? "👤" : ""} ${names[id] || id}`;
  };

  return (
    <div className="results">
      <section className="kpis">
        <Kpi label={`נטל מס כולל ${result.tax_year}`} value={money(result.total_tax_burden)} sub="מס חברות + 81ב + מס הכנסה + ב״ל" />
        {result.companies.map((c: any) => (
          <Kpi key={c.id} label={`🏢 ${names[c.id] || c.id}`} value={money(c.total_tax)}
            sub={`מס חברות ${money(c.corporate_tax)}${Number(c.s81_tax) ? ` · 81ב ${money(c.s81_tax)}` : ""}`} />
        ))}
        {result.individuals.map((i: any) => (
          <Kpi key={i.id} label={`👤 ${names[i.id] || i.id}`} value={money(i.gross_tax)}
            sub={`יתרה ${money(i.balance_due)} · שולי ${pctf(i.marginal_rate)}`} />
        ))}
      </section>

      {alerts.length > 0 && (
        <section className="card">
          <h3>התראות</h3>
          <ul className="alerts">
            {alerts.map((a: any, k: number) => (
              <li key={k} className={`alert ${a.severity}`}>
                <span className="sev">{SEV[a.severity]}</span>
                <span className="who">{label(a.entity)}</span>
                <span className="msg">{a.message}</span>
                {a.ref && <span className="ref">{a.ref}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.companies.map((c: any) => (
        <section className="card" key={c.id}>
          <h3>🏢 {names[c.id] || c.id}</h3>
          <div className="facts">
            <div><span>62א(א1)</span><b className={c.s62a1_applies ? "bad" : "good"}>{c.s62a1_applies ? "חל" : "לא חל"}</b><small>{c.s62a1_reason}</small></div>
            <div><span>שיעור רווחיות</span><b>{pctf(c.profitability_rate)}</b></div>
            <div><span>הכנסה חייבת בחברה</span><b>{money(c.taxable_income)}</b></div>
            <div><span>מס חברות</span><b>{money(c.corporate_tax)}</b></div>
            <div><span>81ב – רווחים עודפים</span><b>{c.s81_applies ? money(c.s81_excess_profits) : "לא חל"}</b><small>{c.s81_exemption}</small></div>
            <div><span>תוספת מס 2%</span><b>{money(c.s81_tax)}</b>{Number(c.s81_min_dividend_to_avoid) > 0 && <small>דיבידנד מינימלי לפטור: {money(c.s81_min_dividend_to_avoid)}</small>}</div>
            <div><span>ניכוי במקור מדיבידנד</span><b>{money(c.dividend_withholding)}</b></div>
            {Number(c.notional_dividend_withholding) > 0 && <div><span>ניכוי 35% – דיבידנד רעיוני</span><b>{money(c.notional_dividend_withholding)}</b></div>}
            <div><span>מקדמות / יתרה</span><b>{money(c.advances_paid)} / {money(c.balance_due)}</b>{c.suggested_advance_rate_pct && <small>שיעור מקדמה מחושב: {pctf(c.suggested_advance_rate_pct)}</small>}</div>
          </div>
          {Object.keys(c.attributed_to).length > 0 && (
            <table className="data">
              <thead><tr><th>מיוחס ל</th>{Object.keys(c.attributed_by_section).map((s) => <th key={s}>{SECTION_LABEL[s] || s}</th>)}</tr></thead>
              <tbody>
                {Object.entries(c.attributed_to).map(([iid, secs]: any) => (
                  <tr key={iid}><td>{names[iid] || iid}</td>{Object.keys(c.attributed_by_section).map((s) => <td key={s} className="num">{money(secs[s])}</td>)}</tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ))}

      {result.individuals.map((i: any) => (
        <section className="card" key={i.id}>
          <h3>👤 {names[i.id] || i.id}</h3>
          <div className="facts">
            <div><span>הכנסה מיגיעה אישית</span><b>{money(i.exertion_income)}</b></div>
            <div><span>הכנסה פסיבית במדרגות</span><b>{money(i.passive_bracket_income)}</b></div>
            {Object.entries(i.special_rate_income).map(([k, v]: any) => <div key={k}><span>{k}</span><b>{money(v)}</b></div>)}
            <div><span>מס לפי מדרגות</span><b>{money(i.bracket_tax)}</b></div>
            <div><span>נקודות זיכוי וזיכויים</span><b>({money(i.credit_points_value)})</b></div>
            <div><span>מס בשיעורים מיוחדים</span><b>{money(i.special_rate_tax)}</b></div>
            <div><span>מס יסף (3% + 2%)</span><b>{money(Number(i.surtax) + Number(i.surtax_capital))}</b></div>
            <div><span>חבות מס</span><b>{money(i.gross_tax)}</b><small>אפקטיבי {pctf(i.effective_rate)} · שולי {pctf(i.marginal_rate)}</small></div>
            {Object.entries(i.credits_and_prepayments).map(([k, v]: any) => <div key={k}><span>{k}</span><b>({money(v)})</b></div>)}
            <div><span>יתרה לתשלום / (החזר)</span><b className={Number(i.balance_due) > 0 ? "bad" : "good"}>{money(i.balance_due)}</b></div>
            <div><span>ב״ל ובריאות {i.nii_is_estimate ? "(הערכה)" : ""}</span><b>{money(Number(i.nii_employee) + Number(i.nii_self_employed) + Number(i.nii_passive))}</b>
              {Number(i.nii_employer_cost) > 0 && <small>חלק מעביד: {money(i.nii_employer_cost)}</small>}</div>
          </div>
        </section>
      ))}

      <section className="card">
        <div className="card-head">
          <h3>פירוק החישוב (Trace)</h3>
          <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="סינון לפי ישות">
            <option value="all">כל הישויות</option>
            {entities.map((e) => <option key={e} value={e}>{label(e)}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table className="data trace">
            <thead><tr><th>ישות</th><th>שלב</th><th>תיאור</th><th>נוסחה</th><th>ערך</th><th>מקור</th></tr></thead>
            <tbody>
              {trace.map((s: any, k: number) => (
                <tr key={k}>
                  <td>{label(s.entity)}</td>
                  <td><span className="tag">{STAGE[s.stage] || s.stage}</span></td>
                  <td>{s.label}{s.note && <div className="muted">{s.note}</div>}</td>
                  <td className="formula" dir="auto">{s.formula}</td>
                  <td className="num">{typeof s.value === "boolean" ? (s.value ? "כן" : "לא") : typeof s.value === "string" && /^-?\d/.test(s.value) ? nf.format(Number(s.value)) : s.value}</td>
                  <td className="muted">{s.ref}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card no-print">
        <button className="ghost" onClick={() => setShowParams(!showParams)}>
          {showParams ? "הסתר" : "הצג"} סטטוס פרמטרים ({unverified.length} שטרם אומתו מול מקור רשמי)
        </button>
        {showParams && (
          <table className="data">
            <thead><tr><th>פרמטר</th><th>סטטוס</th><th>מקור</th></tr></thead>
            <tbody>{result.params_used.map((p: any) => (
              <tr key={p.path}><td dir="ltr">{p.path}</td><td><span className={`tag st-${p.status}`}>{p.status}</span></td><td className="muted" dir="ltr">{p.source}</td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}
