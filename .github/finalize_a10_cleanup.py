from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "specialist_clinic/docs/a10_gate_trigger.md",
    "specialist_clinic/docs/a10_implementation_note.md",
    "specialist_clinic/docs/a10_release_scope.md",
    "specialist_clinic/docs/a10_worklist_contract.md",
    "specialist_clinic/docs/a10_atomicity_contract.md",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
Path(__file__).unlink()
