import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path.home() / "Development" / "Personal" / "ai-credential-manager"), str(ROOT / "scripts")]
spec = importlib.util.spec_from_file_location("credential_engine_import", ROOT / "scripts" / "credential_engine_import.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_new_model_inherits_the_accounts_credential():
    res = {"or_a_old": {"key_var": "K_A"}, "or_a_new": {"key_var": "K_A"}, "or_b_new": {"key_var": "K_B"}}
    mod.inherit_refs(res, {"or_a_old": "cred_1"})
    assert res["or_a_new"]["credential_ref"] == "cred_1"
    assert "credential_ref" not in res["or_b_new"]  # no sibling: stays keyless


def test_known_keyless_resource_is_left_alone():
    res = {"old": {"key_var": "K"}, "keyless": {"key_var": "K"}, "new": {"key_var": "K"}}
    mod.inherit_refs(res, {"old": "cred_1", "keyless": None})
    assert "credential_ref" not in res["keyless"] and res["new"]["credential_ref"] == "cred_1"


def test_existing_ref_kept_and_ambiguity_not_guessed():
    res = {"x": {"key_var": "K", "credential_engine": True}, "y": {"key_var": "K"}, "z": {"key_var": "K"}}
    mod.inherit_refs(res, {"x": "cred_1", "y": "cred_2"})
    assert res["x"]["credential_ref"] == "cred_1" and "credential_engine" not in res["x"]
    assert res["y"]["credential_ref"] == "cred_2"
    assert "credential_ref" not in res["z"]  # two different refs for one variable
