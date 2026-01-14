#!/usr/bin/env python3
"""
Control Assessment Engine
Maps client evidence to framework controls and outputs findings for AI analysis.
NOTE: AI analysis is handled by the central consensus-engine, not here.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def load_framework(framework_path: Path) -> dict:
    """Load the compliance framework JSON."""
    with open(framework_path) as f:
        return json.load(f)


def load_evidence_files(evidence_dir: Path) -> list:
    """Load and catalog all evidence files."""
    evidence_files = []
    for file_path in evidence_dir.iterdir():
        if file_path.is_file():
            evidence_files.append({
                "name": file_path.name,
                "path": str(file_path),
                "type": file_path.suffix.lower().lstrip("."),
                "size": file_path.stat().st_size
            })
    return evidence_files


def extract_text_from_file(file_path: Path) -> Optional[str]:
    """Extract text content from various file types."""
    suffix = file_path.suffix.lower()
    
    try:
        if suffix in [".txt", ".md", ".csv", ".json"]:
            return file_path.read_text(errors="ignore")[:5000]
        
        elif suffix == ".pdf":
            try:
                import PyPDF2
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages[:5]:
                        text += page.extract_text() or ""
                    return text[:5000]
            except Exception:
                return f"[PDF: {file_path.name}]"
        
        elif suffix == ".docx":
            try:
                from docx import Document
                doc = Document(file_path)
                return "\n".join([p.text for p in doc.paragraphs])[:5000]
            except Exception:
                return f"[DOCX: {file_path.name}]"
        
        elif suffix in [".xlsx", ".xls"]:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True)
                text = ""
                for sheet in wb.worksheets[:2]:
                    for row in sheet.iter_rows(max_row=50, values_only=True):
                        text += " ".join([str(c) for c in row if c]) + "\n"
                return text[:5000]
            except Exception:
                return f"[XLSX: {file_path.name}]"
                
    except Exception as e:
        print(f"  Warning: Could not extract from {file_path.name}: {e}")
    
    return None


def match_evidence_to_control(control: dict, evidence_texts: dict) -> dict:
    """
    Simple keyword matching to determine if evidence might satisfy a control.
    Returns a finding dict for AI analysis.
    """
    control_keywords = []
    
    # Extract keywords from control description
    description = control.get("description", "").lower()
    name = control.get("name", "").lower()
    
    # Common evidence types as keywords
    common_evidence = control.get("common_evidence", [])
    for ev in common_evidence:
        control_keywords.extend(ev.lower().split())
    
    # Check which evidence files might be relevant
    matched_evidence = []
    for filename, text in evidence_texts.items():
        text_lower = text.lower()
        # Simple keyword matching
        matches = sum(1 for kw in control_keywords if kw in text_lower)
        if matches > 2:
            matched_evidence.append(filename)
    
    # Determine preliminary status based on evidence availability
    if len(matched_evidence) >= 2:
        status = "potential_compliant"
    elif len(matched_evidence) == 1:
        status = "potential_partial"
    else:
        status = "potential_gap"
    
    return {
        "control_id": control["id"],
        "control_name": control["name"],
        "control_description": control["description"][:500],
        "common_evidence_types": common_evidence,
        "evidence_found": matched_evidence,
        "preliminary_status": status,
        "points_of_focus_count": len(control.get("points_of_focus", [])),
        "requires_ai_analysis": True
    }


def main():
    parser = argparse.ArgumentParser(description="Assess compliance controls")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--framework", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--assessment-type", default="full")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    framework_path = Path(args.framework)
    evidence_dir = Path(args.evidence_dir)
    output_path = Path(args.output)
    
    print(f"🔍 Starting compliance assessment for {args.client_id}")
    
    # Load framework
    framework = load_framework(framework_path)
    controls = framework.get("controls", [])
    print(f"   Loaded {len(controls)} controls from {framework_path.name}")
    
    # Load evidence
    evidence_files = load_evidence_files(evidence_dir)
    print(f"   Found {len(evidence_files)} evidence files")
    
    # Extract text from evidence
    evidence_texts = {}
    for ef in evidence_files:
        text = extract_text_from_file(Path(ef["path"]))
        if text:
            evidence_texts[ef["name"]] = text
    
    print(f"   Extracted text from {len(evidence_texts)} files")
    
    # Map evidence to controls
    findings = []
    for control in controls:
        finding = match_evidence_to_control(control, evidence_texts)
        findings.append(finding)
    
    # Calculate preliminary stats
    potential_compliant = sum(1 for f in findings if f["preliminary_status"] == "potential_compliant")
    potential_partial = sum(1 for f in findings if f["preliminary_status"] == "potential_partial")
    potential_gap = sum(1 for f in findings if f["preliminary_status"] == "potential_gap")
    
    # Build output
    result = {
        "assessment_id": f"{args.client_id}-{framework['framework']['id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "client_id": args.client_id,
        "framework": {
            "id": framework["framework"]["id"],
            "name": framework["framework"]["name"],
            "version": framework["framework"]["version"]
        },
        "assessment_type": args.assessment_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_files": evidence_files,
        "preliminary_summary": {
            "total_controls": len(controls),
            "potential_compliant": potential_compliant,
            "potential_partial": potential_partial,
            "potential_gap": potential_gap
        },
        "findings": findings,
        "note": "Preliminary assessment - requires AI consensus analysis for final determination"
    }
    
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✅ Preliminary assessment complete")
    print(f"   Potential Compliant: {potential_compliant}")
    print(f"   Potential Partial: {potential_partial}")
    print(f"   Potential Gap: {potential_gap}")
    print(f"   Output: {output_path}")
    print(f"   → Sending to AI Consensus Engine for final analysis...")


if __name__ == "__main__":
    main()
