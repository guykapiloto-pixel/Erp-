/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { api } from "./api";
import { money } from "./Results";

function Chart({ points, best }: { points: any[]; best: any }) {
  const W = 640, H = 240, P = 44;
  const xs = points.map((p) => Number(p.salary));
  const ys = points.map((p) => Number(p.total_tax));
  const xMax = Math.max(...xs) || 1;
  const yMin = Math.min(...ys) * 0.95, yMax = Math.max(...ys) * 1.02;
  const x = (v: number) => W - P - (v / xMax) * (W - 2 * P); // RTL: salary grows to the left
  const y = (v: number) => H - P - ((v - yMin) / (yMax - yMin || 1)) * (H - 2 * P);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(Number(p.salary))},${y(Number(p.total_tax))}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="נטל מס כולל לפי גובה משכורת">
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} className="axis" />
      <line x1={W - P} y1={P} x2={W - P} y2={H - P} className="axis" />
      <path d={path} className="line" />
      {points.map((p, i) => <circle key={i} cx={x(Number(p.salary))} cy={y(Number(p.total_tax))} r={p === best ? 6 : 3} className={p === best ? "dot best" : "dot"} />)}
      <text x={W - P} y={H - 12} className="lbl" textAnchor="end">משכורת ←</text>
      <text x={W - P + 6} y={P - 10} className="lbl" textAnchor="end">נטל מס</text>
      <text x={x(Number(best.salary))} y={y(Number(best.total_tax)) - 12} className="lbl best" textAnchor="middle">מיטבי</text>
    </svg>
  );
}

export function Scenarios({ req }: { req: any }) {
  const pairs = req.companies.flatMap((c: any) => (c.shareholders ?? []).filter((s: any) => s.individual_id)
    .map((s: any) => ({ key: `${c.id}|${s.individual_id}`, label: `${c.name || c.id} ← ${req.individuals.find((i: any) => i.id === s.individual_id)?.name || s.individual_id}` })));
  const [pair, setPair] = useState(pairs[0]?.key ?? "");
  const [distribute, setDistribute] = useState(true);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  if (!pairs.length) return <p className="empty">נדרשת חברה שבעל מניותיה הוא יחיד במודל.</p>;
  const run = async () => {
    const [c, i] = pair.split("|");
    setBusy(true); setErr("");
    try { setRes(await api.scenario(req, c, i, 20, distribute)); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="scenarios">
      <div className="card controls">
        <label className="field"><span className="field-label">חברה ← בעל מניות</span>
          <select value={pair} onChange={(e) => setPair(e.target.value)}>{pairs.map((p: any) => <option key={p.key} value={p.key}>{p.label}</option>)}</select>
        </label>
        <label className="field field-bool"><span className="field-label">לחלק את מלוא הרווח כדיבידנד</span>
          <input type="checkbox" checked={distribute} onChange={(e) => setDistribute(e.target.checked)} /></label>
        <button className="primary" onClick={run} disabled={busy}>{busy ? "מחשב…" : "הרץ תרחישים"}</button>
        <p className="note">כל נקודה היא הרצה מלאה של המנוע: משכורת S, ב״ל מעביד כהוצאה, ויתרת הרווח אחרי מס חברות מחולקת כדיבידנד. הייחוס לפי 62א, תוספת 81ב, מס יסף וב״ל מחושבים בכל נקודה.</p>
      </div>
      {err && <p className="error">{err}</p>}
      {res && (
        <>
          <div className="card">
            <h3>מיטבי: משכורת {money(res.best.salary)} · דיבידנד {money(res.best.dividend)} · נטל {money(res.best.total_tax)} ({res.best.effective_rate}%)</h3>
            <p className="muted">רווח מפעילות לפני משכורת בעל המניות: {money(res.profit_before_owner_salary)} · רווח כולל (בסיס לשיעור): {money(res.total_profit_before_owner_salary)}</p>
            <Chart points={res.points} best={res.best} />
          </div>
          <div className="card table-wrap">
            <table className="data">
              <thead><tr><th>משכורת</th><th>דיבידנד</th><th>מס חברות</th><th>81ב</th><th>מס הכנסה</th><th>ב״ל (עובד+מעביד)</th><th>נטל כולל</th><th>שיעור</th><th>נטו לבעלים</th><th>62א(א1)</th></tr></thead>
              <tbody>
                {res.points.map((p: any, k: number) => (
                  <tr key={k} className={p === res.best || (p.salary === res.best.salary && p.total_tax === res.best.total_tax) ? "best-row" : ""}>
                    <td className="num">{money(p.salary)}</td><td className="num">{money(p.dividend)}</td><td className="num">{money(p.corporate_tax)}</td>
                    <td className="num">{money(p.s81_tax)}</td><td className="num">{money(p.income_tax)}</td><td className="num">{money(p.nii_total)}</td>
                    <td className="num"><b>{money(p.total_tax)}</b></td><td className="num">{p.effective_rate}%</td><td className="num">{money(p.owner_net)}</td>
                    <td>{p.s62a1_applies ? "חל" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
