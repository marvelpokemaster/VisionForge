from pathlib import Path
from typing import Dict, Optional


class SessionStore:
    """Maps session ids to run directories produced by `visionforge reconstruct`.
    Read-only against outputs/<run>/ -- this store holds no data of its own
    beyond the mapping itself (no Supabase/DB persistence yet, see Task G).
    Sessions come from two sources: auto-discovery of subdirectories under
    `outputs_root` that look like a real run directory, and explicit
    registration via `register` (a caller-supplied path, so it can point at
    a run directory outside outputs_root too)."""

    def __init__(self, outputs_root: Path):
        self.outputs_root = Path(outputs_root)
        self._registered: Dict[str, Path] = {}

    def register(self, run_dir: Path, session_id: Optional[str] = None) -> str:
        run_dir = Path(run_dir)
        if not run_dir.exists() or not run_dir.is_dir():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        sid = session_id or run_dir.name
        self._registered[sid] = run_dir
        return sid

    @staticmethod
    def _looks_like_run_dir(path: Path) -> bool:
        return (path / "p2" / "room_model.json").exists() or (path / "twin.json").exists()

    def _discovered(self) -> Dict[str, Path]:
        found: Dict[str, Path] = {}
        if self.outputs_root.exists():
            for child in sorted(self.outputs_root.iterdir()):
                if child.is_dir() and self._looks_like_run_dir(child):
                    found[child.name] = child
        return found

    def list_sessions(self) -> Dict[str, Path]:
        merged = self._discovered()
        merged.update(self._registered)  # explicit registrations take precedence
        return merged

    def get(self, session_id: str) -> Optional[Path]:
        return self.list_sessions().get(session_id)
