/* eslint-disable @typescript-eslint/no-explicit-any */
export type Json = any;

async function req(method: string, url: string, body?: unknown): Promise<Json> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* keep status */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  calculate: (request: Json, client_id?: string) => req("POST", "/api/calculate", { request, client_id }),
  scenario: (request: Json, company_id: string, individual_id: string, steps = 20, distribute = true) =>
    req("POST", "/api/scenarios/salary-dividend", { request, company_id, individual_id, steps, distribute }),
  clients: () => req("GET", "/api/clients"),
  client: (id: string) => req("GET", `/api/clients/${id}`),
  saveClient: (id: string | null, name: string, request: Json) =>
    id ? req("PUT", `/api/clients/${id}`, { name, request }) : req("POST", "/api/clients", { name, request }),
  deleteClient: (id: string) => req("DELETE", `/api/clients/${id}`),
  async exportXlsx(request: Json, client_id?: string) {
    const r = await fetch("/api/export/xlsx", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request, client_id }),
    });
    if (!r.ok) throw new Error(`${r.status}`);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tax-${request.tax_year}-${client_id ?? "client"}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};
