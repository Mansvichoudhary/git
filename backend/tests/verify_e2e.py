import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"

def test_e2e():
    print("Testing FinAgent Process 01 & 02 End-to-End...")
    
    # 1. Test Seed Demo
    req = urllib.request.Request(f"{BASE_URL}/reconciliations/REC_DEMO_01/seed-demo", method="POST")
    with urllib.request.urlopen(req) as resp:
        seed_data = json.loads(resp.read().decode())
        print(f"[OK] Seed Demo: {seed_data}")
        assert seed_data["bank_count"] == 8
        assert seed_data["company_count"] == 8

    # 2. Test Input Status
    with urllib.request.urlopen(f"{BASE_URL}/reconciliations/REC_DEMO_01/input-status") as resp:
        status_data = json.loads(resp.read().decode())
        print(f"[OK] Input Status: {status_data}")
        assert status_data["bank_ready"] is True
        assert status_data["company_ready"] is True
        assert status_data["can_start"] is True

    # 3. Test Start Reconciliation
    req = urllib.request.Request(f"{BASE_URL}/reconciliations/REC_DEMO_01/start", method="POST")
    with urllib.request.urlopen(req) as resp:
        start_res = json.loads(resp.read().decode())
        print(f"[OK] Start Reconciliation: {start_res}")
        assert start_res["total_bank_transactions"] == 8
        assert start_res["total_company_transactions"] == 8
        assert start_res["matched_count"] >= 2
        assert start_res["anomalies_count"] >= 5

    # 4. Test Fetch Matches
    with urllib.request.urlopen(f"{BASE_URL}/reconciliations/REC_DEMO_01/matches") as resp:
        matches = json.loads(resp.read().decode())
        print(f"[OK] Matches retrieved: {len(matches)} items")
        assert len(matches) > 0

    # 5. Test Fetch Anomalies with AI investigations
    with urllib.request.urlopen(f"{BASE_URL}/reconciliations/REC_DEMO_01/anomalies") as resp:
        anomalies = json.loads(resp.read().decode())
        print(f"[OK] Anomalies with AI forensic reasoning: {len(anomalies)} items")
        assert len(anomalies) > 0
        
        # Verify forensic AI details
        for a in anomalies:
            assert "finding" in a
            assert "conclusion" in a
            assert "risk" in a
            assert "evidence" in a
            finding_clean = a['finding'].replace('\u20b9', 'INR ')
            print(f"   -> Anomaly [{a['type']}] ({a['severity']}): {finding_clean}")

    # 6. Test Human Review
    first_anom = anomalies[0]
    payload = json.dumps({"action": "CONFIRM_MATCH", "notes": "Auditor approved timing difference"}).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/anomalies/{first_anom['id']}/review",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        rev_res = json.loads(resp.read().decode())
        print(f"[OK] Human Review Recorded: {rev_res}")
        assert rev_res["action"] == "CONFIRM_MATCH"

    # 7. Test Summary Report
    with urllib.request.urlopen(f"{BASE_URL}/reconciliations/REC_DEMO_01/results") as resp:
        summary = json.loads(resp.read().decode())
        print(f"[OK] Reconciliation Summary Report retrieved: {summary['reconciliation_id']}")
        assert summary["total_bank_transactions"] > 0
        assert summary["total_company_transactions"] > 0
        assert "matched_count" in summary
        assert "anomalies_count" in summary

    print("\nALL PROCESS 01 & 02 END-TO-END TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_e2e()
