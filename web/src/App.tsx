/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { api } from "./api";
import { InputEditor } from "./InputEditor";
import { Results } from "./Results";
import { emptyRequest, samples } from "./sample";
import { Scenarios } from "./Scenarios";
import { Transitional } from "./Transitional";

type Tab = "input" | "results" | "scenarios" | "transitional";

export default function App() {
  const [clients, setClients] = useState<any[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [clientName, setClientName] = useState("לקוח חדש");
  const [req, setReq] = useState<any>(emptyRequest());
  const [result, setResult] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("input");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  const refresh = () => api.clients().then(setClients).catch(() => setClients([]));
  useEffect(() => { refresh(); }, []);

  const names: Record<string, string> = {};
  req.individuals.forEach((i: any) => (names[i.id] = i.name || i.id));
  req.companies.forEach((c: any) => (names[c.id] = c.name || c.id));

  const update = (r: any) => { setReq(r); setDirty(true); };
  const load = async (id: string) => {
    const c = await api.client(id);
    setClientId(c.id); setClientName(c.name); setReq(c.request); setResult(null); setTab("input"); setDirty(false);
  };
  const newClient = (template?: any, name = "לקוח חדש") => {
    setClientId(null); setClientName(name); setReq(structuredClone(template ?? emptyRequest())); setResult(null); setTab("input"); setDirty(true);
  };
  const save = async () => {
    try {
      const r = await api.saveClient(clientId, clientName, req);
      setClientId(r.id); setDirty(false); refresh();
    } catch (e: any) { setErr(e.message); }
  };
  const calculate = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.calculate(req, clientId ?? undefined);
      setResult(r.result); setTab("results");
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="app">
      <aside className="sidebar no-print">
        <div className="brand">מחשבון מס<small>יחידים · חברות · 62א · 81ב</small></div>
        <button className="primary block" onClick={() => newClient()}>+ לקוח חדש</button>
        <div className="side-title">לקוחות שמורים</div>
        <ul className="client-list">
          {clients.length === 0 && <li className="muted">אין לקוחות שמורים</li>}
          {clients.map((c) => (
            <li key={c.id} className={c.id === clientId ? "active" : ""}>
              <button onClick={() => load(c.id)}>{c.name}</button>
            </li>
          ))}
        </ul>
        <div className="side-title">דוגמאות לבדיקה</div>
        <ul className="client-list">
          {samples.map((s) => <li key={s.name}><button onClick={() => newClient(s.request, s.name)}>{s.name}</button></li>)}
        </ul>
      </aside>

      <main className="main">
        <header className="topbar no-print">
          <input className="client-name" value={clientName} onChange={(e) => { setClientName(e.target.value); setDirty(true); }} aria-label="שם הלקוח" />
          <div className="actions">
            <button onClick={save}>{dirty ? "שמור •" : "שמור"}</button>
            {clientId && <button className="ghost danger" onClick={async () => { if (confirm("למחוק את הלקוח?")) { await api.deleteClient(clientId); newClient(); refresh(); } }}>מחק</button>}
            <button className="primary" onClick={calculate} disabled={busy}>{busy ? "מחשב…" : "חשב מס"}</button>
          </div>
        </header>
        <nav className="tabs no-print">
          {(["input", "results", "scenarios", "transitional"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)} disabled={t === "results" && !result}>
              {t === "input" ? "נתוני קלט" : t === "results" ? "תוצאות" : t === "scenarios" ? "משכורת מול דיבידנד" : "הוראת שעה"}
            </button>
          ))}
          {result && tab === "results" && (
            <span className="export">
              <button className="ghost" onClick={() => api.exportXlsx(req, clientName).catch((e) => setErr(e.message))}>ייצוא Excel</button>
              <button className="ghost" onClick={() => window.print()}>הדפסה / PDF</button>
            </span>
          )}
        </nav>
        {err && <div className="error" role="alert">{err}<button className="ghost" onClick={() => setErr("")}>✕</button></div>}
        <div className="print-only print-head"><h1>{clientName}</h1><p>דוח חישוב מס לשנת {req.tax_year} · הופק {new Date().toLocaleDateString("he-IL")}</p></div>
        {tab === "input" && <InputEditor req={req} setReq={update} />}
        {tab === "results" && result && <Results result={result} names={names} />}
        {tab === "scenarios" && <Scenarios req={req} />}
        {tab === "transitional" && <Transitional />}
      </main>
    </div>
  );
}
