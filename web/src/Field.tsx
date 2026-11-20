import { useId } from "react";
import type { FieldDef } from "./schema";

/* eslint-disable @typescript-eslint/no-explicit-any */
export function Field({ def, value, onChange, compact }: {
  def: FieldDef; value: any; onChange: (v: any) => void; compact?: boolean;
}) {
  const id = useId();
  let input;
  if (def.type === "bool") {
    input = <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
  } else if (def.type === "select") {
    input = (
      <select id={id} value={value ?? def.options?.[0]?.value} onChange={(e) => onChange(e.target.value)}>
        {def.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (def.type === "text") {
    input = <input id={id} type="text" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  } else {
    input = (
      <input
        id={id}
        type="text"
        inputMode="decimal"
        dir="ltr"
        className="num"
        value={value === null || value === undefined ? "" : String(value)}
        placeholder="0"
        onChange={(e) => {
          const raw = e.target.value.replace(/,/g, "").trim();
          if (raw === "") return onChange(null);
          if (/^-?\d*\.?\d*$/.test(raw)) onChange(raw.endsWith(".") ? raw : Number(raw));
        }}
      />
    );
  }
  if (compact) return input;
  return (
    <label className={`field ${def.type === "bool" ? "field-bool" : ""}`} htmlFor={id} title={def.help}>
      <span className="field-label">{def.label}{def.help && <span className="help" aria-label={def.help}>ⓘ</span>}</span>
      {input}
    </label>
  );
}
