/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { Field } from "./Field";
import { companyGroups, individualGroups, s81Fields, shareholderCols, type Group } from "./schema";

type Props = { req: any; setReq: (r: any) => void };

function clean(o: any) {
  // drop empty values so the engine applies its defaults
  const out: any = {};
  for (const [k, v] of Object.entries(o)) if (v !== null && v !== "" && v !== undefined) out[k] = v;
  return out;
}

function Groups({ groups, obj, set }: { groups: Group[]; obj: any; set: (o: any) => void }) {
  return (
    <>
      {groups.map((g) => (
        <fieldset key={g.title} className="group">
          <legend>{g.title}</legend>
          {g.note && <p className="note">{g.note}</p>}
          <div className="grid">
            {g.fields.map((f) => (
              <Field key={f.key} def={f} value={obj[f.key]} onChange={(v) => set(clean({ ...obj, [f.key]: v }))} />
            ))}
          </div>
        </fieldset>
      ))}
    </>
  );
}

const nextId = (prefix: string, list: any[]) => {
  let n = list.length + 1;
  while (list.some((x) => x.id === `${prefix}${n}`)) n++;
  return `${prefix}${n}`;
};

export function InputEditor({ req, setReq }: Props) {
  const [tab, setTab] = useState<string>("I:" + (req.individuals[0]?.id ?? ""));
  const upd = (patch: any) => setReq({ ...req, ...patch });
  const setInd = (i: number, v: any) => upd({ individuals: req.individuals.map((x: any, j: number) => (j === i ? v : x)) });
  const setCo = (i: number, v: any) => upd({ companies: req.companies.map((x: any, j: number) => (j === i ? v : x)) });

  const addInd = () => {
    const id = nextId("I", req.individuals);
    upd({ individuals: [...req.individuals, { id, name: "", gender: "male", israeli_resident: true }] });
    setTab("I:" + id);
  };
  const addCo = () => {
    const id = nextId("C", req.companies);
    const first = req.individuals[0]?.id;
    upd({ companies: [...req.companies, { id, name: "", is_few_company: true,
      shareholders: first ? [{ individual_id: first, profit_rights_pct: 100, personal_effort: true, resident: true }] : [] }] });
    setTab("C:" + id);
  };
  const remove = (kind: "I" | "C", id: string) => {
    if (!confirm("למחוק?")) return;
    if (kind === "I") upd({ individuals: req.individuals.filter((x: any) => x.id !== id) });
    else upd({ companies: req.companies.filter((x: any) => x.id !== id) });
    setTab("");
  };

  // fall back to the first entity when the selected one doesn't exist (e.g. another client was loaded)
  const keys = [...req.individuals.map((x: any) => "I:" + x.id), ...req.companies.map((x: any) => "C:" + x.id)];
  const active = keys.includes(tab) ? tab : keys[0] ?? "";
  const iIdx = req.individuals.findIndex((x: any) => "I:" + x.id === active);
  const cIdx = req.companies.findIndex((x: any) => "C:" + x.id === active);

  return (
    <div className="editor">
      <fieldset className="group options">
        <legend>הגדרות חישוב</legend>
        <div className="grid">
          <Field def={{ key: "tax_year", label: "שנת מס", type: "select", options: [{ value: "2025", label: "2025" }, { value: "2026", label: "2026" }] }}
            value={String(req.tax_year)} onChange={(v) => upd({ tax_year: Number(v) })} />
          <Field def={{ key: "old", label: "ס' 62א(א) הישן – שיטת ייחוס", type: "select", options: [
            { value: "excess_25", label: "עודף מעל 25% מהמחזור (מדיניות משרד)" }, { value: "full", label: "ייחוס מלא (לשון החוק)" }] }}
            value={req.options?.old_62a_mode} onChange={(v) => upd({ options: { ...req.options, old_62a_mode: v } })} />
          <Field def={{ key: "alt", label: "חלופת דיווח 62א(ג2)", type: "select", options: [
            { value: "attribution", label: "ייחוס + הוצאה בחברה" }, { value: "dividend", label: "חלופת הדיבידנד" }] }}
            value={req.options?.reporting_alternative} onChange={(v) => upd({ options: { ...req.options, reporting_alternative: v } })} />
          {req.tax_year === 2025 && (
            <Field def={{ key: "avg", label: "ממוצע רווחיות 2023–2025", type: "select", options: [
              { value: "auto", label: "אוטומטי – המיטיב" }, { value: "yes", label: "כן" }, { value: "no", label: "לא" }] }}
              value={req.options?.use_2025_average} onChange={(v) => upd({ options: { ...req.options, use_2025_average: v } })} />
          )}
        </div>
      </fieldset>

      <nav className="entity-tabs" aria-label="ישויות">
        {req.individuals.map((x: any) => (
          <button key={x.id} className={active === "I:" + x.id ? "active" : ""} onClick={() => setTab("I:" + x.id)}>
            👤 {x.name || x.id}
          </button>
        ))}
        {req.companies.map((x: any) => (
          <button key={x.id} className={active === "C:" + x.id ? "active" : ""} onClick={() => setTab("C:" + x.id)}>
            🏢 {x.name || x.id}
          </button>
        ))}
        <button className="ghost" onClick={addInd}>+ יחיד</button>
        <button className="ghost" onClick={addCo}>+ חברה</button>
      </nav>

      {iIdx >= 0 && (
        <section className="entity">
          <header className="entity-head">
            <h3>יחיד <code>{req.individuals[iIdx].id}</code></h3>
            <button className="danger ghost" onClick={() => remove("I", req.individuals[iIdx].id)}>מחק</button>
          </header>
          <Groups groups={individualGroups} obj={req.individuals[iIdx]} set={(v) => setInd(iIdx, v)} />
        </section>
      )}
      {cIdx >= 0 && <CompanyEditor req={req} co={req.companies[cIdx]} set={(v) => setCo(cIdx, v)} onRemove={() => remove("C", req.companies[cIdx].id)} />}
      {iIdx < 0 && cIdx < 0 && <p className="empty">בחר יחיד או חברה לעריכה, או הוסף ישות חדשה.</p>}
    </div>
  );
}

function CompanyEditor({ req, co, set, onRemove }: { req: any; co: any; set: (v: any) => void; onRemove: () => void }) {
  const holderOptions = [
    ...req.individuals.map((i: any) => ({ value: "I:" + i.id, label: "👤 " + (i.name || i.id) })),
    ...req.companies.filter((c: any) => c.id !== co.id).map((c: any) => ({ value: "C:" + c.id, label: "🏢 " + (c.name || c.id) })),
    { value: "X:", label: "חיצוני" },
  ];
  const shs = co.shareholders ?? [];
  const setSh = (i: number, v: any) => set({ ...co, shareholders: shs.map((x: any, j: number) => (j === i ? clean(v) : x)) });
  const holderVal = (s: any) => (s.individual_id ? "I:" + s.individual_id : s.company_id ? "C:" + s.company_id : "X:");
  const setHolder = (i: number, val: string) => {
    const s = { ...shs[i] };
    delete s.individual_id; delete s.company_id; delete s.external_name;
    if (val.startsWith("I:")) s.individual_id = val.slice(2);
    else if (val.startsWith("C:")) s.company_id = val.slice(2);
    else s.external_name = "חיצוני";
    setSh(i, s);
  };
  const list = (key: string) => co[key] ?? [];
  const setList = (key: string, v: any[]) => set({ ...co, [key]: v });
  const hist = co.profitability_history ?? {};

  return (
    <section className="entity">
      <header className="entity-head">
        <h3>חברה <code>{co.id}</code></h3>
        <button className="danger ghost" onClick={onRemove}>מחק</button>
      </header>
      <Groups groups={companyGroups.slice(0, 1)} obj={co} set={set} />

      <fieldset className="group">
        <legend>בעלי מניות</legend>
        <div className="table-wrap">
          <table className="edit-table">
            <thead><tr><th>מחזיק</th>{shareholderCols.map((c) => <th key={c.key}>{c.label}</th>)}<th>רווחים נצברים בחברות מעטים אחרות (≥30%)</th><th></th></tr></thead>
            <tbody>
              {shs.map((s: any, i: number) => (
                <tr key={i}>
                  <td><select value={holderVal(s)} onChange={(e) => setHolder(i, e.target.value)}>
                    {holderOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></td>
                  {shareholderCols.map((c) => (
                    <td key={c.key}><Field compact def={c} value={s[c.key] ?? (c.key === "resident" ? true : undefined)} onChange={(v) => setSh(i, { ...s, [c.key]: v })} /></td>
                  ))}
                  <td><input dir="ltr" className="num" placeholder="500000, 700000"
                    value={(s.other_material_holdings_profits ?? []).join(", ")}
                    onChange={(e) => setSh(i, { ...s, other_material_holdings_profits: e.target.value.split(",").map((x) => Number(x.trim().replace(/,/g, ""))).filter((x) => !isNaN(x) && x !== 0) })} /></td>
                  <td><button className="ghost danger" aria-label="הסר" onClick={() => set({ ...co, shareholders: shs.filter((_: any, j: number) => j !== i) })}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="ghost" onClick={() => set({ ...co, shareholders: [...shs, { external_name: "חיצוני", profit_rights_pct: 0, resident: true }] })}>+ בעל מניות</button>
      </fieldset>

      <Groups groups={companyGroups.slice(1)} obj={co} set={set} />

      <fieldset className="group">
        <legend>ס' 62א(א) הישן – פעילות בעל השליטה כנושא משרה / שירותי עובד</legend>
        <p className="note">המחזור וההכנסה החייבת מפעילות זו כלולים בנתוני הפעילות עתירת היגיעה. הם מופחתים ממנה לפני בדיקת 62א(א1).</p>
        <div className="grid">
          <Field def={{ key: "r", label: "מחזור מהפעילות", type: "money" }} value={co.old_62a?.revenue} onChange={(v) => set({ ...co, old_62a: clean({ ...co.old_62a, revenue: v }) })} />
          <Field def={{ key: "t", label: "הכנסה חייבת מהפעילות", type: "money" }} value={co.old_62a?.taxable} onChange={(v) => set({ ...co, old_62a: clean({ ...co.old_62a, taxable: v }) })} />
          <Field def={{ key: "c", label: "בעל השליטה", type: "select", options: [{ value: "", label: "בעלי המניות הפעילים" }, ...req.individuals.map((i: any) => ({ value: i.id, label: i.name || i.id }))] }}
            value={co.old_62a?.controller_id ?? ""} onChange={(v) => set({ ...co, old_62a: clean({ ...co.old_62a, controller_id: v || null }) })} />
        </div>
      </fieldset>

      {req.tax_year === 2025 && (
        <fieldset className="group">
          <legend>היסטוריית רווחיות (הוראת מעבר 2025)</legend>
          <div className="grid">
            {[2023, 2024].map((y) => (["effort_revenue", "effort_taxable", "related_party_payments"] as const).map((k) => (
              <Field key={y + k} def={{ key: k, label: `${y} – ${k === "effort_revenue" ? "מחזור" : k === "effort_taxable" ? "הכנסה חייבת" : "תשלומים לקשורה"}`, type: "money" }}
                value={hist[y]?.[k]} onChange={(v) => {
                  const row = clean({ ...hist[y], [k]: v });
                  const h = { ...hist, [y]: row };
                  if (!row.effort_revenue && !row.effort_taxable) delete h[y];
                  else { row.effort_revenue ??= 0; row.effort_taxable ??= 0; }
                  set({ ...co, profitability_history: h });
                }} />
            )))}
          </div>
        </fieldset>
      )}

      <fieldset className="group">
        <legend>שותפויות מוחזקות</legend>
        {list("partnerships").map((p: any, i: number) => (
          <div className="grid row-card" key={i}>
            {[{ key: "name", label: "שם", type: "text" }, { key: "share_pct", label: "% החזקה ב-31.12", type: "percent" },
              { key: "effort_revenue_share", label: "חלק במחזור מיגיעה", type: "money" }, { key: "effort_taxable_share", label: "חלק בהכנסה החייבת", type: "money" },
              { key: "from_controller_effort", label: "נובע מיגיעת בעל השליטה", type: "bool" }].map((f: any) => (
              <Field key={f.key} def={f} value={p[f.key] ?? (f.key === "from_controller_effort" ? true : undefined)}
                onChange={(v) => setList("partnerships", list("partnerships").map((x: any, j: number) => (j === i ? clean({ ...x, [f.key]: v }) : x)))} />
            ))}
            <button className="ghost danger" onClick={() => setList("partnerships", list("partnerships").filter((_: any, j: number) => j !== i))}>הסר</button>
          </div>
        ))}
        <button className="ghost" onClick={() => setList("partnerships", [...list("partnerships"), { name: "שותפות", share_pct: 0, effort_revenue_share: 0, effort_taxable_share: 0, from_controller_effort: true }])}>+ שותפות</button>
      </fieldset>

      <fieldset className="group">
        <legend>דיבידנדים שהתקבלו – בדיקת 62א(א3)</legend>
        {list("dividends_received_62a3").map((d: any, i: number) => (
          <div className="grid row-card" key={i}>
            {[{ key: "payer_name", label: "החברה המחלקת", type: "text" }, { key: "amount", label: "סכום", type: "money" },
              { key: "company_controls_payer", label: "החברה בעלת שליטה במחלקת", type: "bool" },
              { key: "payer_income_from_controller_effort", label: "הכנסת המחלקת מיגיעת בעל השליטה", type: "bool" }].map((f: any) => (
              <Field key={f.key} def={f} value={d[f.key]}
                onChange={(v) => setList("dividends_received_62a3", list("dividends_received_62a3").map((x: any, j: number) => (j === i ? { ...x, [f.key]: v ?? 0 } : x)))} />
            ))}
            <button className="ghost danger" onClick={() => setList("dividends_received_62a3", list("dividends_received_62a3").filter((_: any, j: number) => j !== i))}>הסר</button>
          </div>
        ))}
        <button className="ghost" onClick={() => setList("dividends_received_62a3", [...list("dividends_received_62a3"), { payer_name: "", amount: 0, company_controls_payer: false, payer_income_from_controller_effort: true }])}>+ דיבידנד</button>
      </fieldset>

      <fieldset className="group">
        <legend>ס' 81ב – רווחים לא מחולקים</legend>
        <div className="grid">
          {s81Fields.map((f) => (
            <Field key={f.key} def={f} value={co.s81?.[f.key]} onChange={(v) => set({ ...co, s81: clean({ ...co.s81, [f.key]: v }) })} />
          ))}
        </div>
      </fieldset>
    </section>
  );
}
