"""Test suite for the RW3 compendium build.

These are *data-integrity* tests: they re-derive facts from the live game install
(same hardcoded GAME path as extract.py) and assert that site/data.json matches
what the game itself renders. They therefore require the game install and can't
run in CI -- run them locally, or let build.py run them automatically as a
post-build gate.

  python tests.py            # run all verifiers

Each verifier exits nonzero on any mismatch; this runner aggregates them.
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# Verifier scripts, each self-contained and exiting nonzero on mismatch.
VERIFIERS = [
    ("unit resists vs bestiary",      "verify_resists.py"),
    ("spell + upgrade descriptions",  "verify_descriptions.py"),
]


def run_all():
    failures = []
    for label, script in VERIFIERS:
        print(f"\n{'='*70}\n# {label}  ({script})\n{'='*70}")
        rc = subprocess.run([sys.executable, os.path.join(HERE, script)]).returncode
        if rc != 0:
            failures.append(label)

    print(f"\n{'='*70}")
    if failures:
        print(f"FAILED: {len(failures)}/{len(VERIFIERS)} -> {', '.join(failures)}")
    else:
        print(f"ALL {len(VERIFIERS)} VERIFIERS PASSED")
    print('='*70)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run_all())
