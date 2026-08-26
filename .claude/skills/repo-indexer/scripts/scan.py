#!/usr/bin/env python3
"""Deterministic groundwork for the repo-indexer skill.

Walks a repository and reports languages by file count, top-level code
directories, manifest files, CI config, container files, docs, a rough test
count, and a conservative secret scan. Prints one JSON object to stdout.

This script never modifies the repository and never prints matched secret
values — only the file and line number, so the indexer can report them
without ever copying the value into a written file.
"""
import json
import os
import re
import sys

IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv",
    "__pycache__", ".next", ".turbo", "target", ".tox", ".mypy_cache",
    ".pytest_cache", "coverage",
}

LANGUAGE_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rb": "Ruby",
    ".java": "Java", ".kt": "Kotlin", ".rs": "Rust", ".c": "C", ".h": "C",
    ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".php": "PHP",
    ".swift": "Swift", ".scala": "Scala", ".ex": "Elixir", ".exs": "Elixir",
    ".sh": "Shell", ".sql": "SQL",
}

MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "setup.py",
    "Gemfile", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "Makefile",
}

CI_PATHS = {
    ".github/workflows", ".gitlab-ci.yml", ".circleci/config.yml",
    "Jenkinsfile", ".travis.yml", "azure-pipelines.yml",
}

CONTAINER_NAMES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}

DOC_NAMES_RE = re.compile(r"(?i)^(readme|contributing|architecture)\b.*")

TEST_PATH_RE = re.compile(
    r"(?i)(^|/)(tests?|specs?|__tests__)(/|$)|"
    r"(_test\.|\.test\.|_spec\.|\.spec\.)"
)

# Conservative, high-signal secret patterns only — false positives are
# expected and are the indexer's job to triage, not this script's.
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                       # GitHub token
]


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and (d == ".github" or not d.startswith("."))
        ]
        for name in filenames:
            yield os.path.join(dirpath, name)


def scan(root):
    languages = {}
    manifests = []
    ci_config = []
    container_files = []
    docs = []
    test_count = 0
    total_files = 0
    top_dirs = {}
    secrets = []

    root = os.path.abspath(root)

    for path in iter_files(root):
        rel = os.path.relpath(path, root)
        total_files += 1

        parts = rel.split(os.sep)
        if len(parts) > 1:
            top_dirs[parts[0]] = top_dirs.get(parts[0], 0) + 1

        base = os.path.basename(path)
        ext = os.path.splitext(base)[1]

        if ext in LANGUAGE_BY_EXT:
            lang = LANGUAGE_BY_EXT[ext]
            languages[lang] = languages.get(lang, 0) + 1

        if base in MANIFEST_NAMES:
            manifests.append(rel)

        if base in CONTAINER_NAMES:
            container_files.append(rel)

        if any(rel == p or rel.startswith(p + os.sep) for p in CI_PATHS):
            ci_config.append(rel)

        if DOC_NAMES_RE.match(base):
            docs.append(rel)

        if TEST_PATH_RE.search(rel):
            test_count += 1

        if ext in {".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".java",
                   ".env", ".yml", ".yaml", ".json", ".cfg", ".ini"}:
            try:
                with open(path, "r", errors="ignore") as f:
                    for lineno, line in enumerate(f, start=1):
                        for pattern in SECRET_PATTERNS:
                            if pattern.search(line):
                                secrets.append({"file": rel, "line": lineno})
                                break
            except (OSError, UnicodeDecodeError):
                pass

    top_code_dirs = sorted(top_dirs.items(), key=lambda kv: -kv[1])[:10]

    greenfield = total_files < 5 and not manifests

    return {
        "root": root,
        "total_files": total_files,
        "greenfield": greenfield,
        "languages_by_file_count": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        "top_code_directories": [{"path": d, "file_count": c} for d, c in top_code_dirs],
        "manifests": sorted(manifests),
        "ci_config": sorted(ci_config),
        "container_files": sorted(container_files),
        "docs": sorted(docs),
        "test_file_count": test_count,
        "secret_count": len(secrets),
        "secret_hits": secrets,
    }


def main():
    if len(sys.argv) != 2:
        print("usage: scan.py <path/to/repo>", file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1]
    if not os.path.isdir(target):
        print(f"error: {target} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(scan(target), indent=2))


if __name__ == "__main__":
    main()
