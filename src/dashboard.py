"""Small demo web app for the SecureHIC claims dashboard."""

from flask import Flask, jsonify, render_template, request

app = Flask(__name__, template_folder="templates", static_folder="static")

PATIENTS = {
    "MBR-1048": {
        "id": "MBR-1048",
        "name": "Amelia Chen",
        "initials": "AC",
        "age": 46,
        "plan": "Silver Choice PPO",
        "member_since": "2021",
        "status": "Active",
        "location": "Portland, OR",
        "care_team": "Northwest Family Health",
        "conditions": ["Type 2 diabetes", "Hypertension"],
    },
    "MBR-2081": {
        "id": "MBR-2081",
        "name": "Marcus Rivera",
        "initials": "MR",
        "age": 63,
        "plan": "Medicare Advantage",
        "member_since": "2018",
        "status": "Active",
        "location": "Austin, TX",
        "care_team": "Hill Country Medical",
        "conditions": ["Osteoarthritis"],
    },
    "MBR-3176": {
        "id": "MBR-3176",
        "name": "Nina Patel",
        "initials": "NP",
        "age": 37,
        "plan": "Gold Plus HMO",
        "member_since": "2023",
        "status": "Active",
        "location": "Seattle, WA",
        "care_team": "Cascade Primary Care",
        "conditions": ["Asthma"],
    },
    "MBR-4023": {
        "id": "MBR-4023",
        "name": "Jordan Brooks",
        "initials": "JB",
        "age": 54,
        "plan": "Silver Choice PPO",
        "member_since": "2020",
        "status": "Active",
        "location": "Denver, CO",
        "care_team": "Front Range Clinic",
        "conditions": ["Hyperlipidemia"],
    },
}

# All records below are fabricated for the interface demo. Scores are illustrative
# review-priority values, not model outputs or conclusions about fraud.
CLAIMS = [
    {
        "id": "CLM-80421",
        "patient_id": "MBR-1048",
        "date": "2025-03-18",
        "service": "Outpatient imaging",
        "provider": "Northwest Imaging Group",
        "category": "Imaging",
        "charged": 4860,
        "allowed": 1740,
        "status": "Needs review",
        "priority": 92,
        "signal": "Similar service billed twice within 48 hours",
    },
    {
        "id": "CLM-80408",
        "patient_id": "MBR-2081",
        "date": "2025-03-17",
        "service": "Physical therapy",
        "provider": "Hill Country Rehab",
        "category": "Therapy",
        "charged": 3280,
        "allowed": 1260,
        "status": "Needs review",
        "priority": 84,
        "signal": "Unusually high visit frequency for this service",
    },
    {
        "id": "CLM-80394",
        "patient_id": "MBR-3176",
        "date": "2025-03-16",
        "service": "Pulmonary function test",
        "provider": "Cascade Specialty Care",
        "category": "Diagnostic",
        "charged": 2140,
        "allowed": 890,
        "status": "In review",
        "priority": 77,
        "signal": "Charge is above the illustrative peer range",
    },
    {
        "id": "CLM-80371",
        "patient_id": "MBR-4023",
        "date": "2025-03-14",
        "service": "Laboratory panel",
        "provider": "Front Range Clinic",
        "category": "Laboratory",
        "charged": 1820,
        "allowed": 620,
        "status": "Needs review",
        "priority": 69,
        "signal": "Repeated billing code combination",
    },
    {
        "id": "CLM-80353",
        "patient_id": "MBR-1048",
        "date": "2025-03-12",
        "service": "Primary care visit",
        "provider": "Northwest Family Health",
        "category": "Office visit",
        "charged": 340,
        "allowed": 186,
        "status": "Reviewed",
        "priority": 18,
        "signal": "Routine claim; no review signal",
    },
    {
        "id": "CLM-80326",
        "patient_id": "MBR-2081",
        "date": "2025-03-10",
        "service": "Cardiology consultation",
        "provider": "Hill Country Medical",
        "category": "Specialist",
        "charged": 720,
        "allowed": 410,
        "status": "Reviewed",
        "priority": 12,
        "signal": "Routine claim; no review signal",
    },
    {
        "id": "CLM-80298",
        "patient_id": "MBR-3176",
        "date": "2025-03-08",
        "service": "Urgent care visit",
        "provider": "Cascade Primary Care",
        "category": "Office visit",
        "charged": 510,
        "allowed": 270,
        "status": "Reviewed",
        "priority": 9,
        "signal": "Routine claim; no review signal",
    },
    {
        "id": "CLM-80267",
        "patient_id": "MBR-4023",
        "date": "2025-03-05",
        "service": "Preventive screening",
        "provider": "Front Range Clinic",
        "category": "Preventive",
        "charged": 260,
        "allowed": 190,
        "status": "Reviewed",
        "priority": 7,
        "signal": "Routine claim; no review signal",
    },
]


def _claim_with_patient(claim):
    return {**claim, "patient": PATIENTS[claim["patient_id"]]["name"]}


@app.get("/")
def index():
    return render_template("dashboard.html")


@app.get("/api/overview")
def overview():
    flagged = [claim for claim in CLAIMS if claim["status"] != "Reviewed"]
    return jsonify(
        {
            "claims_processed": 1284,
            "members_monitored": len(PATIENTS),
            "needs_review": len(flagged),
            "potential_exposure": sum(claim["charged"] for claim in flagged),
            "monthly_claims": [164, 182, 158, 211, 196, 224, 203, 246, 228, 271, 250, 284],
            "monthly_labels": ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"],
            "categories": [
                {"name": "Imaging", "count": 18, "color": "#5c77e8"},
                {"name": "Therapy", "count": 14, "color": "#26a78a"},
                {"name": "Diagnostic", "count": 11, "color": "#e6a543"},
                {"name": "Other", "count": 9, "color": "#a7b0c2"},
            ],
        }
    )


@app.get("/api/claims")
def claims():
    status_filter = request.args.get("status", "").strip().lower()
    query = request.args.get("q", "").strip().lower()
    results = [_claim_with_patient(claim) for claim in CLAIMS]
    if status_filter:
        results = [claim for claim in results if claim["status"].lower() == status_filter]
    if query:
        results = [
            claim
            for claim in results
            if query in " ".join(
                str(claim[key])
                for key in ("id", "patient", "provider", "service", "category", "status")
            ).lower()
        ]
    return jsonify(results)


@app.get("/api/patients")
def patients():
    return jsonify(
        [
            {
                **patient,
                "claim_count": sum(claim["patient_id"] == patient["id"] for claim in CLAIMS),
                "review_count": sum(
                    claim["patient_id"] == patient["id"] and claim["status"] != "Reviewed"
                    for claim in CLAIMS
                ),
            }
            for patient in PATIENTS.values()
        ]
    )


@app.get("/api/patients/<patient_id>")
def patient_profile(patient_id):
    patient = PATIENTS.get(patient_id)
    if patient is None:
        return jsonify({"error": "Patient not found"}), 404
    patient_claims = [
        _claim_with_patient(claim)
        for claim in CLAIMS
        if claim["patient_id"] == patient_id
    ]
    return jsonify({**patient, "claims": patient_claims})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
