#!/usr/bin/env python3
"""Store results in Firestore and upload reports to GCS."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore
from google.cloud import storage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--assessment-id", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--consensus-severity", default="PENDING")
    parser.add_argument("--confidence", default="0")
    args = parser.parse_args()
    
    project_id = os.environ.get("FIREBASE_PROJECT_ID")
    bucket_name = os.environ.get("GCS_BUCKET")
    
    if not project_id or not bucket_name:
        print("❌ Missing FIREBASE_PROJECT_ID or GCS_BUCKET")
        return
    
    # Upload PDF to GCS
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    report_url = ""
    
    report_dir = Path(args.report_dir)
    for pdf in report_dir.glob("*.pdf"):
        blob = bucket.blob(f"reports/{args.client_id}/{args.assessment_id}.pdf")
        blob.upload_from_filename(str(pdf))
        report_url = f"gs://{bucket_name}/reports/{args.client_id}/{args.assessment_id}.pdf"
        print(f"📤 Uploaded: {report_url}")
    
    # Load results
    results_dir = Path(args.results_dir)
    results = {}
    for f in results_dir.glob("*.json"):
        with open(f) as fp:
            results = json.load(fp)
        break
    
    # Store in Firestore
    db = firestore.Client(project=project_id)
    
    assessment_ref = db.collection("clients").document(args.client_id)\
        .collection("assessments").document(args.assessment_id)
    
    assessment_ref.set({
        "assessment_id": args.assessment_id,
        "client_id": args.client_id,
        "framework": results.get("framework", {}),
        "timestamp": datetime.now(timezone.utc),
        "preliminary_summary": results.get("preliminary_summary", {}),
        "ai_consensus": {
            "severity": args.consensus_severity,
            "confidence": float(args.confidence)
        },
        "report_url": report_url,
        "status": "complete"
    })
    
    print(f"✅ Stored assessment: {args.assessment_id}")
    
    # Update client's latest
    client_ref = db.collection("clients").document(args.client_id)
    client_ref.set({
        "latest_assessment": args.assessment_id,
        "latest_assessment_date": datetime.now(timezone.utc),
        "latest_consensus": args.consensus_severity
    }, merge=True)
    
    print(f"✅ Updated client record: {args.client_id}")


if __name__ == "__main__":
    main()
