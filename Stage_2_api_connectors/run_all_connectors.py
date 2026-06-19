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
    ("ERC",                    CONNECTORS_DIR / "erc.py"),
    # ── UK ───────────────────────────────────────────────────────────────────
    ("UKRI",                   CONNECTORS_DIR / "ukri.py"),
    ("Wellcome",               CONNECTORS_DIR / "wellcome.py"),
    ("Royal Society",          CONNECTORS_DIR / "royal_society.py"),
    ("Russell Sage Foundation", CONNECTORS_DIR / "russell_sage.py"),
    # ── Europe (individual countries) ────────────────────────────────────────
    ("ANR France",             CONNECTORS_DIR / "france_anr.py"),
    ("Research Council Finland (AKA)", CONNECTORS_DIR / "finland_aka.py"),
    ("Volkswagen Foundation (DE)", CONNECTORS_DIR / "germany_volkswagen.py"),
    ("DFG Germany",            CONNECTORS_DIR / "germany_dfg.py"),
    ("NCN Poland",             CONNECTORS_DIR / "poland_ncn.py"),
    ("Research Ireland",       CONNECTORS_DIR / "ireland_ri.py"),
    ("Spain AEI",              CONNECTORS_DIR / "spain_aei.py"),
    ("SNSF Switzerland",       CONNECTORS_DIR / "snsf_switzerland.py"),
    # ── North America ────────────────────────────────────────────────────────
    ("USDA NIFA",              CONNECTORS_DIR / "usda_nifa.py"),
    ("NSERC Canada",           CONNECTORS_DIR / "canada_nserc.py"),
    ("CIHR Canada",            CONNECTORS_DIR / "cihr_canada.py"),
    # ── International / Multilateral ─────────────────────────────────────────
    ("HFSP",                   CONNECTORS_DIR / "hfsp.py"),
    # ── Asia Pacific ─────────────────────────────────────────────────────────
    ("JSPS Japan",             CONNECTORS_DIR / "jsps_japan.py"),
    ("JST SATREPS (Japan)",    CONNECTORS_DIR / "jst_satreps.py"),
    ("Australia Grants",       CONNECTORS_DIR / "australia.py"),
    ("ARC Australia",          CONNECTORS_DIR / "arc_australia.py"),
    # ── South America ────────────────────────────────────────────────────────
    ("FAPESP (Brazil)",        CONNECTORS_DIR / "fapesp.py"),
    # ── Other ────────────────────────────────────────────────────────────────
    ("HHMI",                   CONNECTORS_DIR / "hhmi.py"),
    ("Gates Grand Challenges", CONNECTORS_DIR / "gates_grand_challenges.py"),
    ("Templeton Foundation",   CONNECTORS_DIR / "templeton.py"),
    ("Simons Foundation",      CONNECTORS_DIR / "simons_foundation.py"),
    ("Sloan Foundation",       CONNECTORS_DIR / "sloan_foundation.py"),
    ("Marsden Fund (NZ)",      CONNECTORS_DIR / "marsden_fund.py"),
    ("Burroughs Wellcome Fund",CONNECTORS_DIR / "bwf.py"),
    ("Schmidt Sciences",       CONNECTORS_DIR / "schmidt_sciences.py"),
    ("EMBO",                   CONNECTORS_DIR / "embo.py"),
    ("American Heart Association", CONNECTORS_DIR / "aha.py"),
    ("AI Security Institute (AISI)", CONNECTORS_DIR / "aisi.py"),
    ("Future of Life Institute (FLI)", CONNECTORS_DIR / "fli.py"),
    ("Emergent Ventures",          CONNECTORS_DIR / "emergent_ventures.py"),
    ("Commonwealth Scholarships (CSC)", CONNECTORS_DIR / "csc_uk.py"),
    ("NordForsk",              CONNECTORS_DIR / "nordic_nordforsk.py"),
    ("NWO Netherlands",        CONNECTORS_DIR / "nwo.py"),
    ("Research Council Norway",CONNECTORS_DIR / "norway.py"),
    ("Long-Term Future Fund (LTFF)", CONNECTORS_DIR / "ltff.py"),
    ("Survival and Flourishing Fund (SFF)", CONNECTORS_DIR / "sff.py"),
    # ── Think Tanks / Policy Institutes ──────────────────────────────────────
    ("Pacific Forum",           CONNECTORS_DIR / "pacific_forum.py"),
    ("RAND CAST Fellowship",    CONNECTORS_DIR / "rand_cast.py"),
    ("GovAI",                   CONNECTORS_DIR / "govai.py"),
    ("Belfer Center (Harvard)", CONNECTORS_DIR / "belfer_center.py"),
    ("Mila AI Policy Fellowship (Canada)", CONNECTORS_DIR / "mila_ai_policy.py"),
    # ── Harvard University (schools / centers) ──────────────────────────────
    ("Radcliffe Institute (Harvard)", CONNECTORS_DIR / "radcliffe_institute.py"),
    ("Berkman Klein Center (Harvard)", CONNECTORS_DIR / "berkman_klein.py"),
    ("Weatherhead Center (Harvard)", CONNECTORS_DIR / "weatherhead_center.py"),
    ("Ash Center (Harvard)",         CONNECTORS_DIR / "ash_center.py"),
    ("Safra Center (Harvard)",       CONNECTORS_DIR / "safra_center.py"),
    # ── University of Oxford ─────────────────────────────────────────────────
    ("Institute for Ethics in AI (Oxford)", CONNECTORS_DIR / "oxford_ethics_ai.py"),
    ("AfOx Visiting Fellowship (Oxford)",   CONNECTORS_DIR / "oxford_afox.py"),
    # ── University of Cambridge ──────────────────────────────────────────────
    ("CRASSH Visiting Fellowship (Cambridge)",   CONNECTORS_DIR / "crassh_cambridge.py"),
    ("Lauterpacht Centre (Cambridge)",           CONNECTORS_DIR / "lauterpacht_centre.py"),
    # ── Yale University ──────────────────────────────────────────────────────
    ("Yale LGBT Studies Research Fellowship",    CONNECTORS_DIR / "yale_lgbts.py"),
    ("Lewis Walpole Library (Yale)",              CONNECTORS_DIR / "lewis_walpole.py"),
    # ── Princeton University ─────────────────────────────────────────────────
    ("James Madison Program (Princeton)",         CONNECTORS_DIR / "princeton_madison.py"),
    # ── Stanford University ──────────────────────────────────────────────────
    ("Stanford Humanities Center",                CONNECTORS_DIR / "stanford_humanities.py"),
    # ── Massachusetts Institute of Technology ───────────────────────────────
    ("Knight Science Journalism Fellowship (MIT)", CONNECTORS_DIR / "mit_ksj.py"),
    # ── University of California, Berkeley ───────────────────────────────────
    ("Bancroft Library Sidney-Fryer Fellowship (UC Berkeley)", CONNECTORS_DIR / "berkeley_bancroft.py"),
    # ── Columbia University ──────────────────────────────────────────────────
    ("Knight-Bagehot Fellowship (Columbia)", CONNECTORS_DIR / "columbia_knight_bagehot.py"),
    # ── New York University ──────────────────────────────────────────────────
    ("Matthew Power Literary Reporting Award (NYU)", CONNECTORS_DIR / "nyu_matthew_power.py"),
    # ── University of Chicago ────────────────────────────────────────────────
    ("Pritzker Fellows Program (UChicago)", CONNECTORS_DIR / "uchicago_pritzker_fellows.py"),
    # ── University of California, Los Angeles ────────────────────────────────
    ("Gerald Loeb Awards (UCLA)", CONNECTORS_DIR / "ucla_gerald_loeb.py"),
    # ── University College London ────────────────────────────────────────────
    ("Liberating the Collections Fellowship (UCL)", CONNECTORS_DIR / "ucl_liberating_collections.py"),
    # ── London School of Economics ───────────────────────────────────────────
    ("Atlantic Fellows for Social and Economic Equity (LSE)", CONNECTORS_DIR / "lse_afsee.py"),
    # ── University of Pennsylvania ───────────────────────────────────────────
    ("CASI Visiting Scholars/Fellows Program (UPenn)", CONNECTORS_DIR / "penn_casi_visiting.py"),
    # ── Cornell University ───────────────────────────────────────────────────
    ("CGD Non-Resident Fellowship (Cornell)", CONNECTORS_DIR / "cornell_cgd_nonresident.py"),
    # ── Brown University ─────────────────────────────────────────────────────
    ("Howard Fellowship (Brown)", CONNECTORS_DIR / "brown_howard_foundation.py"),
    # ── National University of Singapore ─────────────────────────────────────
    ("Lee Kong Chian NUS-Stanford Fellowship (NUS)", CONNECTORS_DIR / "nus_lee_kong_chian.py"),
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
