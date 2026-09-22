"""The HARD eval set — messier documents, chosen to find the edges the clean 20/20 set can't.

Same `EvalCase` contract as `eval/cases.py`, run the same way (`python -m eval.run_hard`). These documents are
deliberately the shapes that break a grounded RAG in the field:

  - **superseded facts** — an amended figure that supersedes an earlier one in the same long document (does it cite the
    *governing* value, or the first one retrieval happens to surface?).
  - **OCR / scanned noise** — broken line-wraps, stray characters, collapsed spacing (does retrieval still find the fact?).
  - **tables / collapsed columns** — the right value must bind to the right row.
  - **distractor-dense unanswerable** — many similar-looking numbers, none the one asked (does it abstain, or grab a
    lookalike? the hallucination stress).
  - **near-duplicate cross-document** — two almost-identical contracts (does per-document attribution hold, or does one
    contaminate the other?).
  - **paraphrase gap** — the question shares almost no vocabulary with the document (query-expansion stress).
  - **sensitive-in-noise** — planted PII inside OCR noise (does the boundary still tokenize it?).

All documents are synthetic. Some of these are EXPECTED to fail on the first run — that is the point: the failures and
what changed are the deliverable (see the case-study error analysis). Do not tune a document to pass; tune the system.
"""
from __future__ import annotations

from eval.cases import EvalCase

# H1 — a long agreement whose fee is AMENDED later in the same document (the earlier figure is superseded).
AMENDED_MSA = ("amended_msa.txt",
    "MASTER SERVICES AGREEMENT — Vandelay Industries and Kruger Co.\n"
    "1. TERM. This Agreement begins March 1, 2026 and continues for three (3) years.\n"
    "2. FEES. Client shall pay a monthly service fee of $10,000, payable net thirty (30) days.\n"
    "3. SCOPE. Provider will deliver the services described in Exhibit A.\n"
    "... (Exhibits A through D omitted) ...\n"
    "AMENDMENT NO. 1, effective July 1, 2026. The parties agree that Section 2 (FEES) is deleted in its entirety and "
    "replaced with the following: 'Client shall pay a monthly service fee of $12,500, payable net forty-five (45) days.' "
    "All other terms remain in effect. This Amendment supersedes any conflicting prior provision.")

# H2 — a scanned-invoice's text layer: broken wraps, stray marks, collapsed spacing. The total is intact but noisy.
OCR_INVOICE = ("scanned_invoice_ocr.txt",
    "INVO1CE   No.  88213\n"
    "B1ll To:  R. Okafor    Acct  ...4471\n"
    "Desc                     Amt\n"
    "Consulting  (Mar)  . . . . $ 3,200\n"
    "Travel  reimb  . . . . . . $   540\n"
    "Discount . . . . . . . . . -$  240\n"
    "-----------------------------------\n"
    "TOTAL  AM0UNT  DUE  . . .  $ 3,500   (due within 30 days)\n"
    "Rernit to  lockbox  #22  ~  thank  you")

# H3 — a fee schedule as a table; the right value must bind to the right row.
PRICE_TABLE = ("plan_pricing.txt",
    "PLAN PRICING (per month)\n"
    "| Plan       | Monthly | Seats |\n"
    "| Basic      | $500    | 5     |\n"
    "| Pro        | $1,500  | 25    |\n"
    "| Enterprise | $4,000  | 100   |\n"
    "Annual billing receives two months free. Overage seats are billed at $20 each.")

# H4 — distractor-dense: many dollar figures, but NO late fee anywhere. Must abstain.
DISTRACTOR_INVOICE = ("statement_9931.txt",
    "STATEMENT #9931. Opening balance $1,200. Payment received -$1,200. New charges: hosting $340, "
    "storage $85, support $150, taxes $46. Current balance $621. Autopay is enabled. "
    "Questions? Contact billing. Terms: net 30.")

# H5 — two near-identical MSAs (only the party and one number differ). Cross-document contamination stress.
MSA_A = ("northstar_msa.txt",
    "MASTER SERVICES AGREEMENT — Northstar LLC. Monthly fee: $9,000. Net 30. Governing law: Texas. "
    "Auto-renews annually unless 60 days notice.")
MSA_B = ("southgate_msa.txt",
    "MASTER SERVICES AGREEMENT — Southgate LLC. Monthly fee: $11,000. Net 30. Governing law: Texas. "
    "Auto-renews annually unless 60 days notice.")

# H6 — a long policy; the asked fact sits in the middle, surrounded by similar-sounding clauses (retrieval depth).
LONG_POLICY = ("travel_policy.txt",
    "CORPORATE TRAVEL POLICY.\n"
    "Section 1. Booking. All travel must be booked through the approved portal at least 14 days in advance.\n"
    "Section 2. Air. Economy for flights under 6 hours; premium economy is permitted for flights of 6 hours or more.\n"
    "Section 3. Lodging. Reimbursable up to $250 per night in standard metros and $350 in high-cost metros.\n"
    "Section 4. Meals. A per diem of $75 applies; itemized receipts are required for any single meal over $40.\n"
    "Section 5. Ground. Ride-share and standard rental (mid-size or smaller) are reimbursable; luxury classes are not.\n"
    "Section 6. Approvals. Trips over $3,000 total require director sign-off before booking.")

# H7 — paraphrase gap: the question uses none of the document's key words.
PARAPHRASE_DOC = ("severance_clause.txt",
    "Upon involuntary separation without cause, the employee shall receive continuation of base salary for a period "
    "of twelve (12) weeks, together with payment for any accrued but unused vacation.")

# H8 — sensitive data embedded in OCR noise (the boundary must still tokenize before the model).
OCR_SENSITIVE = ("scanned_intake_ocr.txt",
    "PAT1ENT  INTAKE  (scan)\n"
    "Narne:  Jane  Okafor     DOB:  04/12/1985\n"
    "MRN:  A1B2C3D4     Phone:  (212)  555-0170\n"
    "Reason  for  visit:  annual  review.   Balance  due:  $ 130.")


HARD_CASES: list[EvalCase] = [
    # --- answerable-but-hard (RECALL under mess) ---
    EvalCase("h1", "answerable", "What is the current monthly service fee?", [AMENDED_MSA],
             expect_answer="12,500",
             note="Superseded fact: fee amended $10,000 -> $12,500. Citing the original as current is the failure."),
    EvalCase("h2", "answerable", "What is the total amount due on the invoice?", [OCR_INVOICE],
             expect_answer="3,500",
             note="OCR noise: the total is intact but the surrounding text layer is broken/garbled."),
    EvalCase("h3", "answerable", "What is the monthly price of the Pro plan?", [PRICE_TABLE],
             expect_answer="1,500",
             note="Table row-column binding: must not return Basic ($500) or Enterprise ($4,000)."),
    EvalCase("h6", "answerable", "How much can I be reimbursed per night for a hotel in a high-cost city?",
             [LONG_POLICY], expect_answer="350",
             note="Retrieval depth: fact in the middle, surrounded by similar per-limit clauses."),
    EvalCase("h7", "answerable", "If I'm laid off, how many weeks of pay continuation do I get?", [PARAPHRASE_DOC],
             expect_answer="12",   # accept the digit form; the doc says "twelve (12) weeks" and the model may render either
             note="Paraphrase gap: question shares almost no vocabulary with 'involuntary separation without cause'."),

    # --- unanswerable-but-tempting (ABSTENTION / hallucination stress) ---
    EvalCase("h4", "unanswerable", "What is the late payment fee on this statement?", [DISTRACTOR_INVOICE],
             expect_abstain=True,
             note="Distractor-dense: many dollar figures, but no late fee. Grabbing a lookalike is a hallucination."),
    EvalCase("h6b", "unanswerable", "What is the per diem for international travel?", [LONG_POLICY],
             expect_abstain=True,
             note="A plausible fact the policy does not state (only a general $75 per diem, not international)."),

    # --- adversarial cross-document (NON-CONTAMINATION under near-duplication) ---
    EvalCase("h5", "adversarial", "What is Northstar's monthly fee?", [MSA_A, MSA_B],
             expect_answer="9,000", forbid_in_doc=("southgate_msa.txt", "9,000"),
             note="Near-identical MSAs: Northstar=$9,000, Southgate=$11,000. Southgate's answer must not carry $9,000."),

    # --- sensitive in noise (PII HANDLED end-to-end under OCR mess) ---
    EvalCase("h8", "sensitive", "What is the balance due?", [OCR_SENSITIVE],
             expect_answer="130", expect_handled=True,
             note="PII (name/DOB/MRN/phone) embedded in OCR noise must be tokenized before the model; answer still right."),
]
