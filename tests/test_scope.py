"""scope.py: engagement-scope matching and target extraction (pure functions, no tmp
project needed beyond a plain tmp_path for the scope.txt file itself)."""
from ollama_workspace import scope


def test_covers_exact_match():
    assert scope.covers("10.0.0.5", "10.0.0.5")
    assert not scope.covers("10.0.0.5", "10.0.0.6")


def test_covers_cidr_range():
    assert scope.covers("10.0.0.0/24", "10.0.0.55")
    assert not scope.covers("10.0.0.0/24", "10.0.1.1")


def test_covers_wildcard_domain():
    assert scope.covers("*.example.com", "api.example.com")
    assert scope.covers("*.example.com", "deep.sub.example.com")
    assert not scope.covers("*.example.com", "example.com")  # bare domain, not a subdomain
    assert not scope.covers("*.example.com", "evil.com")


def test_extract_candidates_ignores_code_file_tokens():
    found = scope.extract_candidates("edit config.py and run app.js, then check data.json")
    assert found == []


def test_extract_candidates_finds_ips_and_hostnames():
    found = scope.extract_candidates("scan 10.0.0.5 and api.example.com now")
    assert found == ["10.0.0.5", "api.example.com"]


def test_out_of_scope_empty_when_no_scope_defined(tmp_path):
    assert scope.out_of_scope("nmap 8.8.8.8", tmp_path) == []


def test_out_of_scope_flags_only_uncovered_targets(tmp_path):
    scope.add(tmp_path, "10.0.0.0/24")
    scope.add(tmp_path, "*.example.com")
    out = scope.out_of_scope("curl http://api.example.com and ping 8.8.8.8 and 10.0.0.9", tmp_path)
    assert out == ["8.8.8.8"]


def test_add_remove_clear_roundtrip(tmp_path):
    scope.add(tmp_path, "10.0.0.0/24")
    scope.add(tmp_path, "example.com")
    assert scope.targets(tmp_path) == ["10.0.0.0/24", "example.com"]

    assert scope.remove(tmp_path, "1") == "10.0.0.0/24"
    assert scope.targets(tmp_path) == ["example.com"]
    assert scope.remove(tmp_path, "nonexistent") is None

    scope.clear(tmp_path)
    assert scope.targets(tmp_path) == []
