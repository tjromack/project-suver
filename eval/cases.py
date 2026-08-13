"""The labeled eval dataset — Tool × Question × expected trust behavior.

Each case is a small, self-contained document set + a question + what the product SHOULD do. The categories map to
the product's promises:
  - **answerable**   — the fact is in the document → it must surface it (measures RECALL).
  - **unanswerable** — the fact is absent → it must abstain (measures ABSTENTION, the anti-hallucination guard).
  - **adversarial**  — a plausible lure is present (often in a *different* document) → it must not emit the lure
                       in the wrong place (measures NO-FABRICATION and CROSS-DOCUMENT NON-CONTAMINATION).
  - **sensitive**    — planted PII → the boundary must tokenize it before the model, and (if answerable) the
                       answer must still be correct (measures PII-HANDLED end to end).

All documents are synthetic. Cases with one document run through Copilot (`answer_question`); cases with 2+ run
through Ask-across (`ask_across`), so per-document attribution is exercised.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str                                   # answerable | unanswerable | adversarial | sensitive
    question: str
    docs: list[tuple[str, str]]                     # 1+ (name, text)
    expect_answer: str | None = None                # a substring that MUST appear in some answer (recall/correctness)
    expect_abstain: bool = False                    # nothing may be answered (the doc set doesn't support an answer)
    forbid_anywhere: str | None = None              # a substring that must NOT appear in ANY answer (a single-doc lure)
    forbid_in_doc: tuple[str, str] | None = None    # (doc_name, substring) — that doc's answer must NOT contain it
    expect_handled: bool = False                    # the boundary must have handled ≥1 sensitive item before the model
    note: str = ""


# --- shared document snippets (synthetic) ------------------------------------------------------------
ACME = ("acme_msa.txt",
        "MASTER SERVICES AGREEMENT — Acme Corp and Northwind LLC. Term begins January 1, 2026 for two years. "
        "The Agreement auto-renews for successive one-year terms unless either party gives sixty (60) days notice. "
        "Northwind shall pay Acme $12,000 per month, net thirty days. Governed by the laws of the State of New York.")
GLOBEX = ("globex_saas.txt",
          "SOFTWARE SUBSCRIPTION — Globex Inc. Initial Subscription Term: twelve (12) months. The subscription "
          "automatically renews for additional twelve-month periods unless cancelled thirty days prior. Annual "
          "subscription fee is $48,000, invoiced annually in advance. Governing law: the State of California.")
INITECH = ("initech_nda.txt",
           "MUTUAL NDA — Initech and Umbrella Partners. In effect for three (3) years from February 1, 2026. "
           "There are no fees under this Agreement. This NDA does not automatically renew. Governing law is Delaware.")
CONTRACTS = [ACME, GLOBEX, INITECH]

HR_POLICY = ("pto_policy.txt",
             "PAID TIME OFF POLICY. Full-time employees accrue 20 paid vacation days per year, plus 10 paid "
             "holidays. Unused vacation carries over up to 5 days into the next year. Part-time employees accrue "
             "pro-rata. Sick leave is tracked separately and is not paid out on termination.")
INVOICE = ("invoice_5567.txt",
           "INVOICE #5567. Bill to: Dana Reyes, phone 212-555-0170. Subtotal $4,000. Tax $320. "
           "TOTAL AMOUNT DUE: $4,320, payable within 30 days.")


CASES: list[EvalCase] = [
    # --- answerable: recall / correctness --------------------------------------------------------
    EvalCase("a1", "answerable", "What is the monthly fee?", [ACME], expect_answer="12,000"),
    EvalCase("a2", "answerable", "What is the governing law?", [GLOBEX], expect_answer="California"),
    EvalCase("a3", "answerable", "How many paid vacation days do full-time employees receive?", [HR_POLICY],
             expect_answer="20"),
    EvalCase("a4", "answerable", "What is the total amount due?", [INVOICE], expect_answer="4,320"),
    EvalCase("a5", "answerable", "How long is Globex's initial subscription term?", CONTRACTS,
             expect_answer="twelve", note="multi-doc; per-document attribution"),
    EvalCase("a6", "answerable", "What compensation is owed each month under the services agreement?", CONTRACTS,
             expect_answer="12,000", note="paraphrase — exercises DEC 032 expansion + attribution"),

    # --- unanswerable: abstention (the anti-hallucination guard) ----------------------------------
    EvalCase("u1", "unanswerable", "What is the delivery schedule?", [ACME], expect_abstain=True),
    EvalCase("u2", "unanswerable", "Who personally signed the agreement?", [GLOBEX], expect_abstain=True),
    EvalCase("u3", "unanswerable", "What is the satellite launch date?", CONTRACTS, expect_abstain=True),
    EvalCase("u4", "unanswerable", "What is the 401(k) employer match percentage?", [HR_POLICY], expect_abstain=True),
    EvalCase("u5", "unanswerable", "What is the customer's credit score?", [INVOICE], expect_abstain=True),

    # --- adversarial: no fabrication / no cross-document contamination ----------------------------
    EvalCase("x1", "adversarial", "What is the monthly fee under the Acme agreement?", CONTRACTS,
             expect_answer="12,000", forbid_in_doc=("acme_msa.txt", "no fees"),
             note="the NDA says 'no fees' — Acme's answer must not borrow it"),
    EvalCase("x2", "adversarial", "What is the uptime guarantee?",
             [("vendor_sla.txt", "SERVICE LEVELS. The vendor guarantees 99.9% uptime measured monthly."),
              ("basic_plan.txt", "BASIC PLAN. This plan includes email support. It carries no uptime commitment.")],
             forbid_in_doc=("basic_plan.txt", "99.9"),
             note="the SLA doc's 99.9% must not appear in the basic-plan doc's answer"),
    EvalCase("x3", "adversarial", "What is the termination fee?",
             [("svc_terms.txt", "SERVICE TERMS. Either party may terminate with 30 days notice. "
               "The agreement does not specify any termination fee.")],
             expect_abstain=True, note="doc explicitly says the value is absent — must not invent one"),
    EvalCase("x4", "adversarial", "What is this year's budget?",
             [("budget_memo.txt", "BUDGET MEMO. The program budget was cut from $500,000 last year to $300,000 "
               "for the current year.")],
             expect_answer="300,000",
             note="distractor — must report the CURRENT figure ($300,000), not last year's ($500,000); a wrong "
                  "answer would surface 500,000 and miss 300,000. (Mentioning last year's figure as context is "
                  "accurate and grounded, so it is not forbidden.)"),
    EvalCase("x5", "adversarial", "Who is the project lead according to the memo?",
             [("roster.txt", "TEAM ROSTER. Alice Chen is the project lead. Bob Ruiz is the analyst."),
              ("memo.txt", "STATUS MEMO. This memo does not name a project lead; assignments are still pending.")],
             forbid_in_doc=("memo.txt", "Alice"),
             note="the roster's lead must not leak into the memo's answer"),

    # --- sensitive: PII handled before the model, answer still correct ----------------------------
    EvalCase("s1", "sensitive", "What is the renewal date?",
             [("account.txt", "Account managed by Dana Reyes, dana.reyes@northwind.example, 212-555-0170. "
               "The renewal date is June 1, 2026.")],
             expect_answer="June 1", expect_handled=True, note="email+phone tokenized; date answer still works"),
    EvalCase("s2", "sensitive", "Who is the account lead?",
             [("contact.txt", "Contact Michael Torres at mtorres@corp.example. Michael Torres is the account lead.")],
             expect_answer="Michael Torres", expect_handled=True,
             note="the model saw only a token; the answer re-hydrates the real name locally"),
    EvalCase("s3", "sensitive", "What is the policy number?",
             [("member.txt", "Member SSN 123-45-6789. Policy number PN-88213. The plan covers dental and vision.")],
             expect_answer="PN-88213", expect_handled=True, note="SSN tokenized; the non-PII fact answers"),
    EvalCase("s4", "sensitive", "What is the amount due?", [INVOICE],
             expect_answer="4,320", expect_handled=True, note="contact PII tokenized; the invoice total answers"),
]


# --- Retrieval-stress set (DEC 040/046): a SEPARATE recall set for the re-ranking before/after ------------------
# These are deliberately HARD: the answer is stated in words that share almost nothing with the question, and it is
# BURIED among several competing passages that DO share the question's words — so lexical ranking (even with DEC 031
# stemming + DEC 032 expansion) tends to push the real answer below the top-K the answerer reads → it abstains. LLM
# re-ranking (DEC 040) re-orders the wider pool by which passage actually answers, promoting the buried one. This set
# is kept OUT of the flagship SCORECARD (which stays at ceiling) and is run twice — rerank OFF vs ON — by
# `python -m eval.rerank_delta` to produce a reproducible lift number. Needs the real model.
# ⚠️ CALIBRATION: these cases are DESIGNED to bury the answer but are not yet live-verified to show a clean off→on
# delta — run rerank_delta once and tune any case that already answers at baseline (make the doc longer / the answer
# wording more distant) or never answers even with rerank (loosen the burial).

VENDOR_MSA = ("vendor_msa.txt",
    "MASTER SERVICES AGREEMENT between Northwind Analytics LLC (the Client) and Cedar Ridge Consulting, Inc. (the "
    "Vendor), effective March 1, 2026. "
    "Engagement. The Vendor is retained to furnish data-integration and reporting services as an independent "
    "contractor and not as an employee or agent of the Client. "
    "Term. This Agreement continues for twenty-four months and renews automatically for successive twelve-month "
    "periods unless either party gives sixty days written notice. "
    "Compensation. The Client shall remit to the Vendor the sum of twelve thousand dollars ($12,000) at the close of "
    "each calendar month. "
    "Any disbursement arriving more than fifteen days after its due date accrues a surcharge of one and one-half "
    "percent per month. "
    "Expenses. The Client shall reimburse reasonable out-of-pocket costs supported by receipts, not to exceed $2,500 "
    "in any single month without prior written authorization. "
    "Deliverables. The Vendor shall deliver the initial integrated dataset no later than the forty-fifth day following "
    "the Effective Date, with subsequent reporting packages on a fortnightly cadence. "
    "Confidentiality. Each party shall safeguard the other's non-public information for three years beyond termination. "
    "Termination. Either party may terminate for convenience upon ninety days written notice. "
    "Governing Law. This Agreement is governed by the laws of the State of Illinois.")

LATEFEE = ("payment_terms.txt",
    "PAYMENT TERMS. Invoices are issued on the first business day of each month. "
    "The Client shall make all payments by ACH or wire transfer to the account on file. "
    "Payment is due within thirty days of the invoice date. "
    "A remittance advice should accompany each payment. "
    "Should any amount remain unpaid after its due date, a late surcharge of 1.5% per month accrues on the "
    "outstanding balance. "
    "Payment questions may be directed to the billing department. "
    "Partial payments are applied to the oldest outstanding invoice first.")

RENEWAL = ("agreement_terms.txt",
    "GENERAL TERMS. This Agreement begins on the Effective Date and remains in force for two years. "
    "The Agreement renews automatically for one-year periods unless written notice is given. "
    "The parties shall review performance annually at a scheduled meeting. "
    "Either party may terminate for convenience by providing ninety days written notice. "
    "Upon expiration, all licenses granted hereunder immediately cease. "
    "This document is the entire understanding between the parties.")

RERANK_STRESS: list[EvalCase] = [
    EvalCase("r1", "answerable", "What compensation is owed each month?", [VENDOR_MSA], expect_answer="12,000",
             note="Trevor-verified live (abstained rerank-off; answered rerank-on) — the $12,000 span omits the word "
                  "'compensation' and competes with other 'month' spans"),
    EvalCase("r2", "answerable", "What is the penalty for paying late?", [LATEFEE], expect_answer="1.5",
             note="answer is a 'surcharge on overdue balance' — few tokens shared with 'penalty/late'; buried among "
                  "'payment' spans"),
    EvalCase("r3", "answerable", "How can I end the contract early?", [RENEWAL], expect_answer="ninety",
             note="answer is 'terminate for convenience on ninety days notice' — shares no tokens with "
                  "'end/contract/early'; buried among term/renewal spans"),
]
