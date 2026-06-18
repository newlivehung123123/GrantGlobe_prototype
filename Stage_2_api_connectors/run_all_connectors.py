#!/usr/bin/env python3
"""
GrantGlobe — run all API connectors then export grants.json.

Usage (on the VPS):
    cd /opt/grantglobe
    export $(grep DATABASE_URL Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/run_all_connectors.py [--dry-run]

Runs each connector in sequence, then calls export_grants.py, then
commits and pushes grants.json to GitHub Pages.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

CONNECTORS_DIR = Path(__file__).parent
REPO_ROOT = CONNECTORS_DIR.parent

CONNECTORS = [
    # ── US ──────────────────────────────────────────────────────────────────
    ("Grants.gov (US)",        CONNECTORS_DIR / "grants_gov.py"),
    ("NIH Guide",              CONNECTORS_DIR / "nih_guide.py"),
    ("NSF",                    CONNECTORS_DIR / "nsf.py"),
    ("SBIR",                   CONNECTORS_DIR / "sbir.py"),
    # ── EU / Multilateral ────────────────────────────────────────────────────
    ("EU Funding Portal",      CONNECTORS_DIR / "eu_funding_portal.py"),
    # ── UK ───────────────────────────────────────────────────────────────────
    ("UKRI",                   CONNECTORS_DIR / "ukri.py"),
    # ── Europe (individual countries) ────────────────────────────────────────
    ("ANR France",             CONNECTORS_DIR / "france_anr.py"),
    ("Research Council Finland (AKA)", CONNECTORS_DIR / "finland_aka.py"),
    ("Volkswagen Foundation (DE)", CONNECTORS_DIR / "germany_volkswagen.py"),
    ("DFG Germany",            CONNECTORS_DIR / "germany_dfg.py"),
    ("NCN Poland",             CONNECTORS_DIR / "poland_ncn.py"),
    ("Research Ireland",       CONNECTORS_DIR / "ireland_ri.py"),
    ("Spain AEI",              CONNECTORS_DIR / "spain_aei.py"),
    # ── North America ────────────────────────────────────────────────────────
    ("USDA NIFA",              CONNECTORS_DIR / "usda_nifa.py"),
    ("NSERC Canada",           CONNECTORS_DIR / "canada_nserc.py"),
    ("CIHR Canada",            CONNECTORS_DIR / "cihr_canada.py"),
    # ── Asia Pacific ─────────────────────────────────────────────────────────
    ("JSPS Japan",             CONNECTORS_DIR / "jsps_japan.py"),
    ("Australia Grants",       CONNECTORS_DIR / "australia.py"),
    # ── Other ────────────────────────────────────────────────────────────────
    ("NordForsk",              CONNECTORS_DIR / "nordic_nordforsk.py"),
    ("NWO Netherlands",        CONNECTORS_DIR / "nwo.py"),
    ("Research Council Norway",CONNECTORS_DIR / "norway.py"),
]


def run_script(name: str, path: Path, dry_run: bool) -> bool:
    """Run a connector script as a subprocess. Returns True on success."""
    print(f"\n{'='*60}")
    print(f"  Running: {name}")
    print(f"{'='*60}")
    cmd = [sys.executable, str(path)]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, env=os.environ.copy())
    if result.returncode != 0:
        print(f"  WARNING: {name} exited with code {result.returncode}")
        return False
    return True


def run_export(dry_run: bool) -> bool:
    """Run export_grants.py."""
    print(f"\n{'='*60}")
    print("  Running: Export grants.json")
    print(f"{'='*60}")
    export_script = REPO_ROOT / "Stage_4_Static_searchable_interface" / "export_grants.py"
    if not export_script.exists():
        print(f"  ERROR: export_grants.py not found at {export_script}")
        return False
    cmd = [sys.executable, str(export_script)]
    result = subprocess.run(cmd, env=os.environ.copy())
    return result.returncode == 0


def push_to_github() -> bool:
    """Commit and push grants.json to GitHub."""
    print(f"\n{'='*60}")
    print("  Pushing grants.json to GitHub")
    print(f"{'='*60}")
    data_dir = REPO_ROOT / "Stage_4_Static_searchable_interface" / "data"
    grants_json = data_dir / "grants.json"
    if not grants_json.exists():
        print("  ERROR: grants.json not found.")
        return False

    cmds = [
        ["git", "-C", str(REPO_ROOT), "add", str(grants_json)],
        ["git", "-C", str(REPO_ROOT), "commit", "-m",
         f"data: automated connector export {__import__('datetime').date.today()}"],
        ["git", "-C", str(REPO_ROOT), "push", "origin", "main"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            # "nothing to commit" is fine
            if "nothing to commit" in str(result):
                print("  Nothing new to push.")
                return True
            print(f"  WARNING: git command failed: {' '.join(cmd)}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all GrantGlobe API connectors and export."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Pass --dry-run to all connectors (no DB writes)")
    parser.add_argument("--skip-push", action="store_true",
                        help="Skip git push after export")
    parser.add_argument("--only", metavar="NAME",
                        help="Run only the named connector (partial match)")
    args = parser.parse_args()

    connectors = CONNECTORS
    if args.only:
        connectors = [(n, p) for n, p in CONNECTORS
                      if args.only.lower() in n.lower()]
        if not connectors:
            sys.exit(f"No connector matched '{args.only}'. "
                     f"Available: {[n for n, _ in CONNECTORS]}")

    results: dict[str, bool] = {}
    for name, path in connectors:
        if not path.exists():
            print(f"\nSKIPPING {name}: {path} not found.")
            results[name] = False
            continue
        results[name] = run_script(name, path, args.dry_run)

    if not args.dry_run:
        export_ok = run_export(args.dry_run)
        if export_ok and not args.skip_push:
            push_to_github()

    print(f"\n{'='*60}")
    print("  Summary")
    print(f"{'='*60}")
    for name, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {status:6}  {name}")

    if not args.dry_run:
        print(f"  {'OK':6}  Export + Push")

    print()


if __name__ == "__main__":
    main()
