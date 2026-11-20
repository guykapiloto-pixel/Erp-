/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { Field } from "./Field";
import { money } from "./Results";
import type { FieldDef } from "./schema";

const forms: Record<string, { title: string; url: string; fields: FieldDef[]; init: any; note: string }> = {
  liquidation: {
    title: "מסלול פירוק – מס במועד ההעברה",
    url: "/api/transitional/liquidation",
    note: "העברה עד גובה חלק בעל המניות ברווחים הראויים לחלוקה = דיבידנד. היתרה נדחית עד המימוש.",
    init: { material: true },
    fields: [
      { key: "distributable_profits", label: "רווחים ראויים לחלוקה (ס' 94ב)", type: "money" },
      { key: "holding_pct", label: "שיעור החזקה %", type: "percent" },
      { key: "value_transferred", label: "שווי הנכסים שהועברו לבעל המניות", type: "money" },
      { key: "material", label: "בעל מניות מהותי (30%)", type: "bool" },
      { key: "company_cost_of_assets", label: "יתרת מחיר מקורי בחברה (חלופה 1)", type: "money" },
      { key: "holder_share_cost", label: "עלות המניות לבעל המניות (חלופה 2)", type: "money" },
    ],
  },
  asset: {
    title: "מסלול העברת נכס – מס במועד ההעברה",
    url: "/api/transitional/asset-transfer",
    note: "בסיס = עלות מופחתת פחות הלוואה מובטחת. עד גובה הרווחים: דיבידנד; לאחר מכן קיזוז יתרת זכות; היתרה בשיעור מרבי.",
    init: { material: true },
    fields: [
      { key: "depreciated_cost", label: "עלות מופחתת / יתרת מחיר מקורי", type: "money" },
      { key: "secured_bank_loan", label: "הלוואה בנקאית מובטחת בנכס", type: "money" },
      { key: "distributable_profits", label: "רווחים ראויים לחלוקה", type: "money" },
      { key: "shareholder_credit_balance", label: "יתרת זכות ספציפית של בעל המניות", type: "money" },
      { key: "material", label: "בעל מניות מהותי", type: "bool" },
      { key: "accumulated_profits_2024", label: "רווחים נצברים לסוף 2024 (בדיקת 5%)", type: "money" },
    ],
  },
  sale: {
    title: "מכירה עתידית של נכס שהועבר – פיצול לינארי",
    url: "/api/transitional/later-sale",
    note: "החלק שעד ההעברה ממוסה בשיעור 47% ללא קיזוז הפסדים; החלק שלאחריה בשיעור ס' 91 / ס' 48א.",
    init: { material: false, real_estate: false, inventory: false },
    fields: [
      { key: "real_gain", label: "רווח הון ריאלי / שבח ריאלי", type: "money" },
      { key: "acquisition_date", label: "יום הרכישה (YYYY-MM-DD)", type: "text" },
      { key: "transfer_date", label: "יום ההעברה / תחילת הפירוק", type: "text" },
      { key: "sale_date", label: "יום המכירה", type: "text" },
      { key: "material", label: "בעל מניות מהותי", type: "bool" },
      { key: "real_estate", label: "זכות במקרקעין", type: "bool" },
      { key: "inventory", label: "מלאי", type: "bool" },
    ],
  },
};

function Calc({ k }: { k: string }) {
  const f = forms[k];
  const [v, setV] = useState<any>(f.init);
  const [out, setOut] = useState<any>(null);
  const [err, setErr] = useState("");
  const run = async () => {
    setErr("");
    const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== null && x !== ""));
    const r = await fetch(f.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) { setErr(typeof j.detail === "string" ? j.detail : "יש להשלים את כל השדות הנדרשים"); setOut(null); } else setOut(j);
  };
  return (
    <section className="card">
      <h3>{f.title}</h3>
      <p className="note">{f.note}</p>
      <div className="grid">{f.fields.map((d) => <Field key={d.key} def={d} value={v[d.key]} onChange={(x) => setV({ ...v, [d.key]: x })} />)}</div>
      <p><button className="primary" onClick={run}>חשב</button></p>
      {err && <p className="error">{err}</p>}
      {out && (
        <>
          <table className="data">
            <thead><tr><th>שלב</th><th>נוסחה</th><th>ערך</th><th>מקור</th></tr></thead>
            <tbody>{out.steps.map((s: any, i: number) => (
              <tr key={i}><td>{s.label}</td><td className="formula">{s.formula}</td><td className="num">{/^-?\d/.test(String(s.value)) ? money(s.value) : s.value}</td><td className="muted">{s.ref}</td></tr>
            ))}</tbody>
          </table>
          <ul className="muted">{out.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
        </>
      )}
    </section>
  );
}

export function Transitional() {
  return (
    <div>
      <p className="note">הוראת השעה (ס' 6 לחוק, חוזר 03/2025) – פירוק חברת מעטים או העברת נכסים לבעלי המניות בשנת 2025, בדחיית מס. החלון נסגר; המחשבונים משמשים לבדיקת הדיווח לשנת 2025 ולחישוב המס במכירה עתידית של נכס שהועבר.</p>
      {Object.keys(forms).map((k) => <Calc key={k} k={k} />)}
    </div>
  );
}
