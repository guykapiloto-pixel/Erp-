// Demo clients based on the official worked examples, so results can be compared to known numbers.
export const emptyRequest = () => ({
  tax_year: 2026,
  individuals: [{ id: "I1", name: "", gender: "male", israeli_resident: true }],
  companies: [] as unknown[],
  options: { old_62a_mode: "excess_25", reporting_alternative: "attribution", use_2025_average: "auto" },
});

export const samples: { name: string; request: unknown }[] = [
  {
    name: "דוגמה: משרד אדריכלים (חוזר 62א, נספח ה')",
    request: {
      tax_year: 2025,
      individuals: [{ id: "A", name: "בעל המניות", gender: "male", israeli_resident: true }],
      companies: [{
        id: "C1", name: "אדריכלים בע\"מ", is_few_company: true,
        shareholders: [{ individual_id: "A", profit_rights_pct: 100, personal_effort: true, resident: true }],
        effort_revenue: 1000000, effort_expenses: 400000, other_income: 300000, other_expenses: 100000,
        accumulated_profits_prev: 800000,
        s81: { accumulated_profits_tax_alt: 800000 },
      }],
      options: { old_62a_mode: "excess_25", reporting_alternative: "attribution", use_2025_average: "auto" },
    },
  },
  {
    name: "דוגמה: חלופת הדיבידנד (הוראת ביצוע 9/2026)",
    request: {
      tax_year: 2025,
      individuals: [{ id: "A", name: "בעל המניות", gender: "male", israeli_resident: true }],
      companies: [{
        id: "C1", name: "חברת ייעוץ בע\"מ", is_few_company: true,
        shareholders: [{ individual_id: "A", profit_rights_pct: 100, personal_effort: true, resident: true }],
        effort_revenue: 1000000, accumulated_profits_prev: 800000,
      }],
      options: { old_62a_mode: "excess_25", reporting_alternative: "dividend", use_2025_average: "auto" },
    },
  },
  {
    name: "דוגמה: שרשור החזקות + 81ב",
    request: {
      tax_year: 2026,
      individuals: [{ id: "A", name: "בעל השליטה", gender: "female", israeli_resident: true, salary_external: 0 }],
      companies: [
        { id: "H", name: "חברת החזקות", shareholders: [{ individual_id: "A", profit_rights_pct: 100, resident: true }] },
        {
          id: "S", name: "חברה בת", shareholders: [{ company_id: "H", profit_rights_pct: 100 }],
          effort_revenue: 3000000, effort_expenses: 2400000, dividends_declared: 100000, dividend_to_parent_track: "main",
          accumulated_profits_prev: 2500000,
          s81: { accumulated_profits_tax_alt: 2500000, deductible_expenses: 2400000 },
        },
      ],
      options: { old_62a_mode: "excess_25", reporting_alternative: "attribution", use_2025_average: "auto" },
    },
  },
];
