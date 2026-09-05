#!/usr/bin/env python3
"""Publish an assessment result.

The ICIT standard sink is the storeAssessmentResults Cloud Function, which owns
the Firestore write. The original script wrote Firestore directly from the
workflow, which meant the runner needed Firestore credentials and the multi-tenant
partitioning rule existed in two places. Posting to the function instead leaves
one writer and one place where `clients/{client_id}/assessments/{assessment_id}`
is decided.

The POST uses stdlib urllib, so this step needs no google-cloud packages. Report
upload to GCS stays optional and is skipped with a message when the client
library or the bucket is not configured.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironclad.ids import slugify  # noqa: E402

TIMEOUT_SECONDS = 60

# The endpoint is operator-supplied (a secret, or --endpoint). urllib's urlopen
# honours file:// and every other scheme urllib understands, so a mistyped or
# tampered endpoint could turn "publish a result" into "read a local file and
# report it as an HTTP response". http.client speaks only HTTP, which makes that
# structurally impossible rather than merely checked -- the scheme check below is
# then about which of the two HTTP schemes is acceptable, not about safety.
ALLOWED_SCHEMES = ("https", "http")


def find_result(results_dir: Path) -> dict | None:
    """The assessment document in a directory, preferring the canonical name."""
    candidates = [results_dir / "assessment.json", *sorted(results_dir.glob("*.json"))]
    for path in candidates:
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict) and "assessment_id" in document:
            return document
    return None


def post_result(endpoint: str, payload: dict, api_key: str = "") -> tuple[bool, str]:
    """POST the record to the ingest function. Returns (ok, message)."""
    scheme = urllib.parse.urlparse(endpoint).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return False, (
            f"refusing to publish to a {scheme or 'schemeless'} endpoint; "
            f"the ingest endpoint must be one of {', '.join(ALLOWED_SCHEMES)}"
        )
    if scheme == "http" and not endpoint.startswith(("http://localhost", "http://127.0.0.1")):
        # Plain http off the loopback would put an assessment result, and the
        # ingest key, on the wire in clear.
        return False, "refusing to publish over plain http to a remote host; use https"

    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.hostname:
        return False, "the ingest endpoint has no host"

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ironclad-compliance/1.0",
        "Content-Length": str(len(body)),
    }
    if api_key:
        headers["X-Ingest-Key"] = api_key

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    connection_class = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_class(parsed.hostname, parsed.port, timeout=TIMEOUT_SECONDS)

    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        detail = response.read().decode("utf-8", "replace")[:400]
        # 2xx is stored; anything else is reported with the upstream's own words,
        # which is what makes an ingest misconfiguration diagnosable from the log.
        return 200 <= response.status < 300, f"HTTP {response.status}: {detail}"
    except Exception as exc:  # noqa: BLE001 — reported, never raised into the workflow log
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        connection.close()


def upload_reports(bucket_name: str, client_id: str, assessment_id: str, report_dir: Path) -> str:
    """Upload the rendered reports to GCS. Returns the base URI, or ''."""
    try:
        from google.cloud import storage  # noqa: PLC0415 — optional dependency
    except ImportError:
        print("  report upload skipped: google-cloud-storage is not installed")
        return ""

    files = [p for p in report_dir.rglob("*") if p.suffix.lower() in (".pdf", ".html")]
    if not files:
        print("  report upload skipped: no report files found")
        return ""

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    prefix = f"reports/{client_id}/{assessment_id}"
    for path in files:
        blob = bucket.blob(f"{prefix}/{path.name}")
        blob.upload_from_filename(str(path))
        print(f"  uploaded gs://{bucket_name}/{prefix}/{path.name}")
    return f"gs://{bucket_name}/{prefix}/"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish an assessment result.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--assessment-id", default="")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--report-dir", default="")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("STORE_RESULTS_URL", ""),
        help="storeAssessmentResults URL (or set STORE_RESULTS_URL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the record, post nothing")
    args = parser.parse_args(argv)

    client_id = slugify(args.client_id)
    results_dir = Path(args.results_dir)

    document = find_result(results_dir)
    if document is None:
        print(f"no assessment document found in {results_dir}", file=sys.stderr)
        return 2

    assessment_id = args.assessment_id or document.get("assessment_id", "")
    if not assessment_id:
        print("no assessment id, in the arguments or the document", file=sys.stderr)
        return 2

    report_url = ""
    bucket = os.environ.get("GCS_BUCKET", "")
    if args.report_dir and bucket:
        report_dir = Path(args.report_dir)
        if report_dir.is_dir():
            report_url = upload_reports(bucket, client_id, assessment_id, report_dir)
    elif args.report_dir:
        print("  report upload skipped: GCS_BUCKET is not set")

    record = {
        "client_id": client_id,
        "assessment_id": assessment_id,
        # scan_id keeps the field name the shared ingest surface already uses, so
        # one Cloud Function shape serves the scanning products and this one.
        "scan_id": assessment_id,
        "scan_type": "compliance-assessment",
        "product": "ironclad-compliance",
        "status": "completed",
        "framework": document.get("framework", {}),
        "summary": document.get("summary", {}),
        "controls": document.get("controls", []),
        "findings": document.get("findings", []),
        "remediation": document.get("remediation", {}),
        "consensus": document.get("consensus"),
        "warnings": document.get("warnings", []),
        "failed_modules": document.get("failed_modules", {}),
        "audit": document.get("audit", {}),
        "report_url": report_url,
        "engine_version": document.get("engine_version", ""),
    }

    if args.dry_run or not args.endpoint:
        if not args.endpoint and not args.dry_run:
            print("no --endpoint and no STORE_RESULTS_URL: printing the record instead of posting")
        print(json.dumps({k: v for k, v in record.items() if k != "controls"}, indent=2)[:4000])
        return 0

    ok, message = post_result(args.endpoint, record, os.environ.get("INGEST_API_KEY", ""))
    print(f"  store: {message}")
    if not ok:
        print("failed to store the assessment result", file=sys.stderr)
        return 1

    summary = record["summary"]
    print(
        f"stored {assessment_id} for {client_id}: "
        f"readiness {summary.get('readiness_score', '?')}%, "
        f"{summary.get('gap', '?')} control(s) not met"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
