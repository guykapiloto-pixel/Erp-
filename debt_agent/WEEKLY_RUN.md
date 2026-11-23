# ריצה שבועית – ניתוח גבייה

1. **ייצוא הלוח** "יעל EK-גבייה" (קריאה בלבד) עם ArtifactData `list`, `out_dir=<board>`, `limit` 1000, לאוספים:
   `hyp`, `custList`, `cfile`, `contacts`.
2. **הרצה:**
   ```bash
   cd debt_agent
   python -m debtcheck hyp --config config.hyp.yaml --board <board> --out collections_report_<YYYY-MM-DD>.xlsx \
          [--csv report.csv]
   ```
   `--csv` הוא דוח המסמכים המלא מ-Hyp, ובלעדיו אין בקרת נוסחה. החוב הפתוח והתשלומים נלקחים מהלוח, ש-Hyp מעדכן.
3. **בקרות שחייבות לעבור לפני הפצה:**
   - סך החוב הפתוח שחושב שווה לסה"כ בלוח (הפרש עד ₪2).
   - אין שגיאה `BOARD_TOTAL_DIFF`.
4. **הפצה:** הגיליון הראשון בדוח, "רשימת השבוע", הוא רשימת העבודה של מנהלת הגבייה.
5. **נתוני לקוחות** (ייצוא הלוח, CSV, דוחות) לא נכנסים ל-git.
