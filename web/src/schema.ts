// Form definitions: every engine input field with its Hebrew label and help text.
export type FieldDef = {
  key: string;
  label: string;
  type?: "money" | "number" | "bool" | "select" | "text" | "percent";
  options?: { value: string; label: string }[];
  help?: string;
};

export type Group = { title: string; fields: FieldDef[]; note?: string };

export const individualGroups: Group[] = [
  {
    title: "פרטים אישיים",
    fields: [
      { key: "name", label: "שם", type: "text" },
      { key: "gender", label: "מין", type: "select", options: [{ value: "male", label: "גבר" }, { value: "female", label: "אישה" }] },
      { key: "age", label: "גיל בסוף השנה", type: "number", help: "מגיל 60 הכנסה פסיבית ממוסה במדרגות רגילות (ס' 121)" },
      { key: "israeli_resident", label: "תושב ישראל", type: "bool" },
      { key: "credit_points", label: "נקודות זיכוי (ריק = ברירת מחדל)", type: "number", help: "ברירת מחדל: 2.25 לתושב, +0.5 לאישה" },
    ],
  },
  {
    title: "הכנסה מיגיעה אישית",
    note: "משכורת מחברה שבמודל מוזנת בכרטיס החברה, בטבלת בעלי המניות",
    fields: [
      { key: "salary_external", label: "משכורת ממעסיקים אחרים (ברוטו)", type: "money" },
      { key: "business_income", label: "הכנסה מעסק / משלח יד (נטו)", type: "money" },
      { key: "other_exertion_income", label: "הכנסה אחרת מיגיעה אישית", type: "money" },
    ],
  },
  {
    title: "הכנסה שאינה מיגיעה אישית (מדרגות, מינימום 31%)",
    fields: [
      { key: "rental_income_taxable", label: "שכירות במסלול מדרגות", type: "money" },
      { key: "other_passive_income", label: "הכנסה פסיבית אחרת", type: "money" },
    ],
  },
  {
    title: "הכנסות בשיעור מס מיוחד",
    fields: [
      { key: "dividends_external", label: "דיבידנד מחברות שאינן במודל", type: "money" },
      { key: "dividends_external_material", label: "בעל מניות מהותי במחלקת (30%)", type: "bool" },
      { key: "capital_gains_real", label: "רווח הון ריאלי", type: "money" },
      { key: "capital_gains_material", label: "רווח הון – בעל מניות מהותי (30%)", type: "bool" },
      { key: "interest_unlinked", label: "ריבית לא צמודה (15%)", type: "money" },
      { key: "interest_linked", label: "ריבית צמודה (25%)", type: "money" },
    ],
  },
  {
    title: "ניכויים, זיכויים ותשלומים",
    fields: [
      { key: "deductions", label: "ניכויים מההכנסה (ס' 47 וכו')", type: "money" },
      { key: "tax_credits", label: "זיכויים בש\"ח (ס' 45א וכו')", type: "money" },
      { key: "donations", label: "תרומות (ס' 46)", type: "money" },
      { key: "notional_65_balance", label: "יתרת 'מחסנית' – 65% מדיבידנד רעיוני", type: "money", help: "תקנה 3(ה): דיבידנד בפועל עד יתרה זו נחשב כלא חולק" },
      { key: "tax_withheld", label: "מס שנוכה במקור", type: "money" },
      { key: "advances_paid", label: "מקדמות ששולמו", type: "money" },
      { key: "nii_passive_liable", label: "לחייב ב\"ל על הכנסה פסיבית (הערכה)", type: "bool" },
    ],
  },
];

export const companyGroups: Group[] = [
  {
    title: "פרטי החברה",
    fields: [
      { key: "name", label: "שם החברה", type: "text" },
      { key: "is_few_company", label: "חברת מעטים (ס' 76)", type: "bool" },
    ],
  },
  {
    title: "רווח והפסד לפי סוג פעילות",
    note: "'הכנסה אחרת' לפי ס' 62א(ד): ריבית, דיבידנד, שכירות, תמורה ממכירת נכס/נ\"ע/מקרקעין. תמלוגים ומלאי קבלן אינם הכנסה אחרת.",
    fields: [
      { key: "effort_revenue", label: "מחזור מפעילות עתירת יגיעה אישית", type: "money" },
      { key: "effort_expenses", label: "הוצאות ספציפיות לפעילות זו (כולל משכורות)", type: "money" },
      { key: "other_income", label: "הכנסה אחרת (פסיבית)", type: "money" },
      { key: "other_expenses", label: "הוצאות ספציפיות להכנסה האחרת", type: "money" },
      { key: "shared_expenses", label: "הוצאות משותפות (ייוחסו יחסית למחזור)", type: "money" },
      { key: "exempt_dividends_received", label: "דיבידנד בין-חברתי פטור (ס' 126(ב))", type: "money" },
      { key: "loss_carryforward", label: "הפסד מועבר", type: "money" },
    ],
  },
  {
    title: "ס' 62א – נתוני תחולה",
    fields: [
      { key: "accumulated_profits_prev", label: "רווחים נצברים לסוף השנה הקודמת (ס' 77(א))", type: "money", help: "בניכוי סכומים שכבר יוחסו לפי 3(ט1), 62א, 64, 64א" },
      { key: "related_party_payments", label: "תשלומים לחברה קשורה", type: "money" },
      { key: "related_party_declared", label: "הוגשה הצהרה (טופס 1122)", type: "bool" },
    ],
  },
  {
    title: "דיבידנד ומקדמות",
    fields: [
      { key: "dividends_declared", label: "דיבידנד שהוכרז בשנה", type: "money" },
      {
        key: "dividend_to_parent_track", label: "דיבידנד לחברת אם – מסלול", type: "select",
        options: [
          { value: "main", label: "ראשי – ניכוי 35% + דיבידנד רעיוני" },
          { value: "alternative", label: "חלופי – העברה לבעל המניות הסופי" },
          { value: "exempt", label: "פטור בלבד (לא נספר ל-81ב)" },
        ],
      },
      { key: "advances_paid", label: "מקדמות ששולמו", type: "money" },
      { key: "advance_rate_pct", label: "שיעור מקדמות נוכחי %", type: "percent" },
    ],
  },
];

export const s81Fields: FieldDef[] = [
  { key: "accumulated_profits_tax_alt", label: "רווחים נצברים – חלופת מס", type: "money" },
  { key: "accumulated_profits_accounting_alt", label: "רווחים נצברים – חלופה חשבונאית", type: "money" },
  { key: "exempt_accumulated_profits", label: "רווחים נצברים פטורים", type: "money" },
  { key: "deductible_expenses", label: "מגן הוצאות – הגבוה מבין הוצאות השנה וממוצע 3 שנים", type: "money", help: "ללא הוצאות בגין נכסים מיוחדים (פחת, מימון)" },
  { key: "depreciated_assets_cost", label: "מגן נכסים – עלות נכסים בניכוי נכסים מיוחדים, הון מניות והלוואות קשורים", type: "money", help: "ס' 81ג; נכסים מיוחדים: ני\"ע, מזומנים, פיקדונות, הלוואות, מקרקעין להשקעה" },
  { key: "start_date_profits_remaining", label: "יתרת רווחים ליום התחילה 31.12.2024 (מסלול 20%, 2025–2030)", type: "money" },
  { key: "exempt_profits_option", label: "חלופת רווחים פטורים", type: "select", options: [{ value: "2", label: "2 – שבע שנים קודמות" }, { value: "1", label: "1 – מההתאגדות, בניכוי נכסים מיוחדים (ללא מגן נכסים)" }] },
  { key: "cash_shield_share_pct", label: "חלק במגן הכספי % (פיצול בין חברות באותה שליטה)", type: "percent" },
  { key: "dividends_qualifying", label: "דיבידנד לעניין 81ב (ריק = אוטומטי)", type: "money" },
];

export const shareholderCols: FieldDef[] = [
  { key: "profit_rights_pct", label: "% רווחים", type: "percent" },
  { key: "control_pct", label: "% שליטה", type: "percent" },
  { key: "relatives_group", label: "קבוצת קרובים", type: "text" },
  { key: "personal_effort", label: "יגיעה אישית", type: "bool" },
  { key: "salary_from_company", label: "משכורת מהחברה", type: "money" },
  { key: "resident", label: "תושב", type: "bool" },
  { key: "controls_other_active_company", label: "שולט בחברה פעילה אחרת", type: "bool" },
];

export const SECTION_LABEL: Record<string, string> = {
  a_old: "62א(א)", a1: "62א(א1)", a2: "62א(א2)", a3: "62א(א3)",
};
