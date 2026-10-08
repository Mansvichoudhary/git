import os
import json
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from app.schemas.reconciliation import AnomalyItem, AIInvestigationResult


class AIInvestigationAgent:
    """
    Forensic AI Investigation Agent (Sections 20, 21, 22, 23).
    Investigates financial exceptions deterministically identified by Process 02.
    Critical safety rule: AI explains the findings and suggests actions;
    AI never invents financial numbers or overrides deterministic calculations.
    """

    @classmethod
    def investigate_anomaly(cls, anomaly: AnomalyItem) -> AIInvestigationResult:
        """
        Runs investigation via Gemini LLM if GEMINI_API_KEY is available,
        or uses deterministic financial expert forensic rule reasoning.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")

                prompt = (
                    "You are a Senior Forensic Financial Auditor investigating a bank reconciliation exception.\n"
                    f"Anomaly Type: {anomaly.type}\n"
                    f"Severity: {anomaly.severity}\n"
                    f"Amount Discrepancy: ₹{anomaly.amount_difference}\n"
                    f"Date Difference Days: {anomaly.date_difference_days}\n"
                    f"Deterministic Evidence: {json.dumps(anomaly.evidence)}\n\n"
                    "Provide a structured audit investigation in strict JSON format with keys:\n"
                    "- finding (concise summary of what occurred)\n"
                    "- conclusion (auditor conclusion on legitimacy)\n"
                    "- confidence (float between 0.0 and 1.0)\n"
                    "- risk (one of: LOW, MEDIUM, HIGH, CRITICAL)\n"
                    "- evidence (list of concise bullet strings)\n"
                    "- recommended_action (one of: 'Confirm match', 'Investigate vendor with invoice', 'Request clarification', 'Flag as duplicate payment')\n"
                    "Do NOT invent numbers. Use only provided facts."
                )
                resp = model.generate_content(prompt)
                raw_text = resp.text.strip()
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()

                parsed = json.loads(raw_text)
                return AIInvestigationResult(
                    id=f"INV_{uuid.uuid4().hex[:10].upper()}",
                    anomaly_id=anomaly.id,
                    finding=parsed.get("finding", "Auditor investigation completed"),
                    anomaly_type=anomaly.type,
                    conclusion=parsed.get("conclusion", "Review recommended"),
                    confidence=float(parsed.get("confidence", 0.90)),
                    risk=parsed.get("risk", anomaly.severity),
                    evidence=parsed.get("evidence", anomaly.evidence),
                    recommended_action=parsed.get("recommended_action", "Review and confirm match"),
                    ai_model="gemini-1.5-flash",
                    created_at=datetime.now(timezone.utc).isoformat()
                )
            except Exception:
                pass

        # Deterministic Expert Forensic Reasoning Fallback
        return cls._generate_expert_forensic_investigation(anomaly)

    @classmethod
    def _generate_expert_forensic_investigation(cls, anomaly: AnomalyItem) -> AIInvestigationResult:
        """
        Deterministic expert audit rulebook for forensic investigations.
        """
        a_type = anomaly.type
        evidence = anomaly.evidence.copy()

        if a_type == "DATE_MISMATCH":
            finding = f"Likely timing difference ({anomaly.date_difference_days} days)"
            conclusion = f"Transaction matches in amount and description; posting lag of {anomaly.date_difference_days} day(s) is typical for inter-bank clearing cycles (RTGS/NEFT/UPI)."
            confidence = 0.94
            risk = "LOW"
            rec_action = "Confirm match (legitimate timing mismatch)"

        elif a_type == "AMOUNT_MISMATCH":
            finding = f"Amount mismatch of ₹{anomaly.amount_difference:,.2f}"
            conclusion = f"Primary payee and date correlate, but net amount diverges by ₹{anomaly.amount_difference:,.2f}. Possible bank processing surcharge, GST deduction, or currency exchange fee."
            confidence = 0.86
            risk = "HIGH" if anomaly.amount_difference > 500 else "MEDIUM"
            rec_action = "Inspect invoice and bank surcharge line items before confirming"

        elif a_type == "DUPLICATE_TRANSACTION":
            finding = "Potential duplicate transaction detected"
            conclusion = f"Identical monetary amount appears in close proximity. High risk of vendor double-payment or inadvertent dual batch entry."
            confidence = 0.91
            risk = "CRITICAL" if anomaly.severity == "HIGH" else "HIGH"
            rec_action = "Mark duplicate and request immediate accounts verification"

        elif a_type == "COMPOSITE_MATCH":
            finding = "Composite / Split payment matched"
            conclusion = "The single bank transaction equals the combined sum of two distinct company ledger records."
            confidence = 0.89
            risk = "LOW"
            rec_action = "Confirm composite match"

        elif a_type == "MISSING_IN_COMPANY":
            finding = "Unrecorded bank withdrawal / transaction"
            conclusion = "Bank statement shows a transaction that has no corresponding ledger entry in internal company books. Possible unrecorded direct debit, standing order, or core banking fee."
            confidence = 0.92
            risk = "HIGH"
            rec_action = "Create journal entry in accounting ledger or investigate counterparty"

        elif a_type == "MISSING_IN_BANK":
            finding = "Outstanding company ledger entry"
            conclusion = "Company accounts show an entry with no settlement on the bank statement. Typical of unpresented cheques or pending customer deposit clearance."
            confidence = 0.88
            risk = "MEDIUM"
            rec_action = "Monitor next statement cycle for bank clearing"

        else:
            finding = "Financial exception identified"
            conclusion = "Transaction requires human auditor verification."
            confidence = 0.80
            risk = "MEDIUM"
            rec_action = "Review transaction details"

        return AIInvestigationResult(
            id=f"INV_{uuid.uuid4().hex[:10].upper()}",
            anomaly_id=anomaly.id,
            finding=finding,
            anomaly_type=a_type,
            conclusion=conclusion,
            confidence=confidence,
            risk=risk,
            evidence=evidence,
            recommended_action=rec_action,
            ai_model="finagent-deterministic-forensic-engine",
            created_at=datetime.now(timezone.utc).isoformat()
        )
