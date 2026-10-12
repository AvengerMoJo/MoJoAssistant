import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("secret_scan", REPO / "scripts" / "secret_scan.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)

REAL = "sk-or-v1-" + "ab12" * 16


def test_real_shaped_keys_are_found_and_never_echoed_whole():
    for line in (f'"api_key": "{REAL}",', f"OPENAI={REAL}", 'x = "AIza' + "A" * 35 + '"',
                 "-----" + "BEGIN RSA PRIVATE KEY-----", "token: ghp_" + "a" * 36):
        hits = ss.scan_line(line)
        assert hits, line
        assert all(len(first4) == 4 for _, first4 in hits)


def test_placeholders_and_references_pass():
    for line in ('"api_key": "sk-or-v1-your-openrouter-account-a",', '"key_var": "OPEN_ROUTER_KEY"',
                 'api_key = os.environ["OPEN_ROUTER_KEY"]', '"api_key": "<your key here>"',
                 f'"api_key": "{REAL}"  # secret-scan: allow', 'password = ""', "token_budget = 12000"):
        assert ss.scan_line(line) == [], line


def test_diff_reports_file_and_line_for_added_lines_only():
    diff = ("+++ b/config/x.json\n@@ -1,2 +10,3 @@\n context\n"
            f'-"api_key": "{REAL}"\n+"name": "ok"\n+"api_key": "{REAL}"\n')
    assert {h[:2] for h in ss.scan_diff(diff)} == {("config/x.json", 12)}


def _repo(tmp_path):
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    return git


def _run_hook(tmp_path):
    return subprocess.run(["python3", str(REPO / "scripts" / "secret_scan.py"), "--staged"],
                          cwd=tmp_path, capture_output=True, text=True)


def test_hook_blocks_a_force_added_ignored_file(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / ".gitignore").write_text("local.json\n")
    (tmp_path / "local.json").write_text("{}\n")
    git("add", "-f", "local.json", ".gitignore")
    r = _run_hook(tmp_path)
    assert r.returncode == 1 and "local.json" in r.stdout and "matches .gitignore" in r.stdout


def test_hook_blocks_a_key_and_prints_no_key(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "c.json").write_text(f'{{"api_key": "{REAL}"}}\n')
    git("add", "c.json")
    r = _run_hook(tmp_path)
    assert r.returncode == 1 and "c.json:1" in r.stdout and REAL not in r.stdout


def test_hook_passes_a_clean_commit(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "ok.json").write_text('{"key_var": "OPEN_ROUTER_KEY"}\n')
    git("add", "ok.json")
    assert _run_hook(tmp_path).returncode == 0
