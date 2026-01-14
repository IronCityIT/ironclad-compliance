#!/usr/bin/env python3
"""
Framework Update Checker
Checks official sources for updates to compliance frameworks.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


FRAMEWORK_SOURCES = {
    "soc2": {
        "name": "SOC 2 Trust Service Criteria",
        "check_url": "https://www.aicpa.org/resources/landing/system-and-organization-controls-soc-suite-of-services",
        "keywords": ["trust services criteria", "TSC"],
        "current_version": "2017"
    },
    "nist-csf": {
        "name": "NIST Cybersecurity Framework",
        "check_url": "https://www.nist.gov/cyberframework",
        "keywords": ["CSF 2.0", "cybersecurity framework"],
        "current_version": "2.0"
    },
    "pci-dss": {
        "name": "PCI Data Security Standard",
        "check_url": "https://www.pcisecuritystandards.org/document_library/",
        "keywords": ["PCI DSS", "4.0"],
        "current_version": "4.0"
    },
    "hipaa": {
        "name": "HIPAA Security Rule",
        "check_url": "https://www.hhs.gov/hipaa/for-professionals/security/index.html",
        "keywords": ["security rule"],
        "current_version": "current"
    }
}


def check_for_updates(framework_id: str, config: dict) -> dict:
    """Check a framework's official page for update indicators."""
    result = {
        "framework_id": framework_id,
        "name": config["name"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "update_detected": False,
        "details": None,
        "error": None
    }
    
    try:
        headers = {"User-Agent": "IronClad-Compliance-Checker/1.0"}
        response = requests.get(config["check_url"], headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text().lower()
        
        # Look for update indicators
        update_phrases = ["new version", "updated", "revision", "latest"]
        for phrase in update_phrases:
            if phrase in page_text:
                result["details"] = f"Found '{phrase}' - manual review recommended"
                result["update_detected"] = True
                break
                
    except Exception as e:
        result["error"] = str(e)
    
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", default="")
    parser.add_argument("--output", default="updates.json")
    args = parser.parse_args()
    
    frameworks = {args.framework: FRAMEWORK_SOURCES[args.framework]} if args.framework else FRAMEWORK_SOURCES
    
    results = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "updates_found": False,
        "frameworks": [],
        "checks": []
    }
    
    for fid, config in frameworks.items():
        print(f"Checking {config['name']}...")
        check = check_for_updates(fid, config)
        results["checks"].append(check)
        
        if check.get("update_detected"):
            results["updates_found"] = True
            results["frameworks"].append(fid)
    
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"Results: {args.output}")


if __name__ == "__main__":
    main()
