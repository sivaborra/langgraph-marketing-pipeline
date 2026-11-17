"""Shared run store: local publish and rejection.

Used by the LangGraph publish/rejected nodes and the ADK publish step
alike. Local only - no LinkedIn, no WordPress, no external call.
"""

import os
import shutil


def publish(draft, deck_path, run_id, out_root="published"):
    """Copy draft + deck into published/<run_id>/. Returns the output dir."""
    out_dir = os.path.join(out_root, run_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "draft.md"), "w", encoding="utf-8") as f:
        f.write(draft)
    if deck_path and os.path.exists(deck_path):
        shutil.copy(deck_path, os.path.join(out_dir, os.path.basename(deck_path)))
    return out_dir

