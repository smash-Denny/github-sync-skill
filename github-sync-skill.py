#!/usr/bin/env python3
"""
强制分类 GitHub 同步脚本
Denny-skill 专用，禁止直接调用 GitHub API 创建 Denny-* 仓库。

使用方法：
    python3 github-sync-skill.py <skill_base_path> [--repo-name <name>]

功能：
1. 自动识别 skill 类型（书籍拆解类 vs 独立工具类）
2. 根据类型选择正确的 repo 结构
3. 创建/更新 GitHub 仓库，上传所有文件
4. 可选归档旧repo（--archive-patterns）

铁律：所有 smash-Denny/Denny-* 仓库必须通过此脚本创建，禁止直接 curl API。
"""

import sys
import json
import subprocess
import os
import tempfile
import argparse
import base64
import re
from pathlib import Path

GITHUB_USER = "smash-Denny"
TOKEN_FILE = "/home/gem/secrets/.github_pat"

def get_token():
    with open(TOKEN_FILE) as f:
        t = f.read().strip()
        if t.startswith("ghp_"):
            return t
    raise ValueError("GitHub token not found")

TOKEN = get_token()

LICENSE_TEMPLATE = """MIT License

Copyright (c) 2026 Denny Xu / 杭州登旭野科技有限公司

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""

# ============================================================
# 类型判断（自动，无需人工）
# ============================================================

def classify_skill_type(base_path: str) -> str:
    """
    自动识别 skill 类型。

    书籍拆解类：有 BOOK_OVERVIEW.md（同书多个skill，形成体系）
    独立工具类：只有 SKILL.md（单skill，独立功能）
    """
    base = Path(base_path)
    if (base / "BOOK_OVERVIEW.md").exists():
        return "book"
    elif (base / "SKILL.md").exists():
        return "tool"
    else:
        print(f"ERROR: 无法识别 skill 类型。")
        print(f"  书籍拆解类必须有 BOOK_OVERVIEW.md")
        print(f"  独立工具类必须有 SKILL.md")
        sys.exit(1)

# ============================================================
# GitHub API 基础操作
# ============================================================

def github_api(method: str, path: str, data=None, retry=2):
    for attempt in range(retry + 1):
        cmd = [
            "curl", "-s", "-X", method,
            "-H", f"Authorization: token {TOKEN}",
            "-H", "Content-Type: application/json",
            f"https://api.github.com/{path}",
        ]
        if data is not None:
            cmd += ["-d", json.dumps(data)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            if attempt == retry:
                sys.exit(f"GitHub API error after {retry+1} attempts")
    return {}

def get_sha(repo: str, path: str) -> str | None:
    d = github_api("GET", f"repos/{GITHUB_USER}/{repo}/contents/{path}")
    return d.get("sha")

def upload_file(repo: str, local_path: str, repo_path: str, sha=None) -> str:
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    data = {"message": f"Add {repo_path}", "content": content}
    if sha:
        data["sha"] = sha
    d = github_api("PUT", f"repos/{GITHUB_USER}/{repo}/contents/{repo_path}", data)
    return d.get("content", {}).get("html_url") or d.get("message") or "ERROR"

def write_upload_str(repo: str, content_str: str, repo_path: str, sha=None) -> str:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(content_str)
        path = f.name
    try:
        return upload_file(repo, path, repo_path, sha)
    finally:
        os.unlink(path)

def create_or_get_repo(repo_name: str, description: str) -> str:
    d = github_api("POST", "user/repos", {
        "name": repo_name,
        "description": description,
        "private": False,
        "has_issues": True,
    })
    if "id" in d:
        print(f"  ✅ Created: {repo_name}")
        return repo_name
    errors_str = str(d.get("errors", [])).lower()
    if "already exists" in errors_str or "name already" in d.get("message", "").lower():
        print(f"  ⚠️  Already exists: {repo_name}")
        return repo_name
    print(f"  ❌ Create failed: {d.get('message', d)}")
    sys.exit(1)

def archive_repo(repo_name: str, note: str = ""):
    d = github_api("PATCH", f"repos/{GITHUB_USER}/{repo_name}", {
        "archived": True,
        "description": f"[ARCHIVED] {note}"
    })
    if d.get("archived"):
        print(f"  ✅ Archived: {repo_name}")
    else:
        print(f"  ⚠️  Archive failed: {repo_name} — {d.get('message', '')[:60]}")

def archive_patterns(patterns: list[str], note: str):
    """归档与模式匹配的未归档repo"""
    print(f"\n  [Archive] patterns: {patterns}")
    d = github_api("GET", f"users/{GITHUB_USER}/repos?per_page=100")
    if not isinstance(d, list):
        print(f"  ⚠️  Cannot list repos")
        return
    for repo in d:
        name = repo["name"]
        if repo.get("archived"):
            continue
        for pattern in patterns:
            if pattern.lower() in name.lower():
                archive_repo(name, note)
                break

# ============================================================
# 生成 meta SKILL.md（book-class 入口）
# ============================================================

def generate_meta_skill_md(book_slug: str, book_name: str, skill_dirs: list[str]) -> str:
    """
    生成根目录 meta SKILL.md，作为 skill 包的入口。
    内容来自 INDEX.md 的核心结构。
    """
    slug_list = "\n".join([f"- **{s}**" for s in skill_dirs])

    return f"""---
name: {book_slug}
description: |
  《{book_name}》蒸馏出的 {len(skill_dirs)} 个 Skills 合集。
  通过下方 skills/ 目录下各 Skill 的 SKILL.md 触发。
  触发词请参考各 Skill 的 description 字段。
source_book: {book_name}
tags: [denny-cangjie, book-distillation]
---

# {book_name} — Skills 合集

## 包含 Skills

{slug_list}

## 使用说明

各 Skill 的详细说明、触发词、执行步骤，参见 `skills/` 目录下对应的 SKILL.md。

---

*由 Denny-cangjie v1.7 蒸馏产出*
"""

def generate_meta_json(book_slug: str, book_name: str, skill_dirs: list[str], version="v1.0.0") -> str:
    skills = []
    for s in skill_dirs:
        skills.append({
            "slug": s,
            "name": s.replace("-", " ").title(),
            "type": "framework",
            "role": "skill"
        })
    return json.dumps({
        "name": book_slug,
        "version": version,
        "description": f"从《{book_name}》蒸馏的 {len(skill_dirs)} 个 Skills",
        "source_book": book_name,
        "distilled_by": "Denny-cangjie v1.7",
        "skills": skills
    }, ensure_ascii=False, indent=2)

def generate_changelog(initial_version="v1.0.0") -> str:
    return f"""# Changelog

All notable changes will be documented in this file.

## {initial_version}

- 初始版本：完成 Phase 0-5 蒸馏
- 包含 {initial_version} 个 Skills
"""

# ============================================================
# 独立工具类上传（一skill一repo）
# ============================================================

def sync_tool_skill(base_path: str, repo_name: str, skill_name: str, description: str):
    print(f"\n{'='*50}")
    print(f"Type: 独立工具类 (tool)")
    print(f"Repo: {repo_name}")
    print(f"{'='*50}")

    base = Path(base_path)
    repo_name = repo_name or f"Denny-{skill_name}"

    create_or_get_repo(repo_name, description)

    for fname in ["SKILL.md", "test-prompts.json", "README.md"]:
        src = base / fname
        if src.exists():
            sha = get_sha(repo_name, fname)
            print(f"  {fname}: {upload_file(repo_name, str(src), fname, sha)}")

    if not (base / "README.md").exists():
        content = f"# {skill_name}\n\n{description}\n\n---\n*Denny-cangjie skill*\n"
        sha = get_sha(repo_name, "README.md")
        print(f"  README.md (auto): {write_upload_str(repo_name, content, 'README.md', sha)}")

    sha = get_sha(repo_name, "LICENSE")
    print(f"  LICENSE: {write_upload_str(repo_name, LICENSE_TEMPLATE, 'LICENSE', sha)}")

    print(f"\n✅ {repo_name} sync complete")

# ============================================================
# 书籍拆解类上传（一书一repo，正确的目录结构）
# ============================================================

def sync_book_skills(base_path: str, repo_name: str, book_name: str, description: str):
    """
    正确的书籍类 repo 结构：
    {book}/
    ├── SKILL.md                    ← meta入口（自动生成）
    ├── _meta.json                  ← 版本+skill清单（自动生成）
    ├── CHANGELOG.md               ← 版本历史（首次自动生成）
    ├── LICENSE
    ├── distillation-log.schema.json
    ├── references/
    │   ├── BOOK_OVERVIEW.md
    │   └── INDEX.md
    └── skills/
        ├── {skill-1}/SKILL.md
        │   └── test-prompts.json
        └── {skill-2}/SKILL.md
            └── test-prompts.json
    """
    print(f"\n{'='*50}")
    print(f"Type: 书籍拆解类 (book)")
    print(f"Repo: {repo_name}")
    print(f"Path: {base_path}")
    print(f"{'='*50}")

    base = Path(base_path)
    create_or_get_repo(repo_name, description)

    # ── 发现所有 skill 子目录 ──
    skill_dirs = []
    for item in sorted(base.iterdir()):
        if item.is_dir() and (item / "SKILL.md").exists():
            skill_dirs.append(item.name)

    if not skill_dirs:
        print("ERROR: 未找到任何 skill 子目录（需要包含 SKILL.md）")
        sys.exit(1)

    print(f"  发现 {len(skill_dirs)} 个 skills: {', '.join(skill_dirs)}")

    # ── references/（BOOK_OVERVIEW + INDEX）──
    print(f"\n  [references/]")
    ref_files = [
        ("BOOK_OVERVIEW.md", base / "BOOK_OVERVIEW.md"),
        ("INDEX.md", base / "INDEX.md"),
    ]
    for name, src in ref_files:
        if src.exists():
            sha = get_sha(repo_name, f"references/{name}")
            print(f"    {name}: {upload_file(repo_name, str(src), f'references/{name}', sha)}")
        else:
            print(f"    {name}: ⚠️  源文件不存在，跳过")

    # ── README.md（book-class 专用：复制 INDEX.md 作为根目录 README）──
    # 约定：INDEX.md 格式兼容 README 展示场景，同时作为 GitHub repo 首页说明
    readme_src = base / "INDEX.md"
    if readme_src.exists():
        sha_readme = get_sha(repo_name, "README.md")
        with open(readme_src, "r", encoding="utf-8") as f:
            readme_content = f.read()
        print(f"\n  [root README]")
        print(f"    README.md (from INDEX.md): {write_upload_str(repo_name, readme_content, 'README.md', sha_readme)}")
    else:
        print(f"\n  [root README]")
        print(f"    README.md: ⚠️  INDEX.md 不存在，无法生成 README（book-class repo 应有 INDEX.md）")

    # ── skills/（各 skill SKILL.md + test-prompts）──
    print(f"\n  [skills/]")
    for skill_folder in sorted(skill_dirs):
        folder_path = base / skill_folder
        print(f"\n    --- {skill_folder} ---")

        sha = get_sha(repo_name, f"skills/{skill_folder}/SKILL.md")
        print(f"      SKILL.md: {upload_file(repo_name, str(folder_path / 'SKILL.md'), f'skills/{skill_folder}/SKILL.md', sha)}")

        tp = folder_path / "test-prompts.json"
        if tp.exists():
            sha = get_sha(repo_name, f"skills/{skill_folder}/test-prompts.json")
            print(f"      test-prompts.json: {upload_file(repo_name, str(tp), f'skills/{skill_folder}/test-prompts.json', sha)}")

    # ── 根目录 meta 文件（自动生成）──
    print(f"\n  [root meta files]")

    # CHANGELOG.md（仅首次生成，已有则跳过）
    sha_changelog = get_sha(repo_name, "CHANGELOG.md")
    if sha_changelog is None:
        print(f"    CHANGELOG.md: {write_upload_str(repo_name, generate_changelog(), 'CHANGELOG.md', None)}")
    else:
        print(f"    CHANGELOG.md: already exists, skipped")

    # distillation-log.schema.json（仅首次生成）
    sha_schema = get_sha(repo_name, "distillation-log.schema.json")
    if sha_schema is None:
        schema_content = json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "distillation-log",
            "description": " Denny-cangjie 蒸馏日志",
            "type": "object"
        }, ensure_ascii=False, indent=2)
        print(f"    distillation-log.schema.json: {write_upload_str(repo_name, schema_content, 'distillation-log.schema.json', None)}")

    # _meta.json
    meta_content = generate_meta_json(repo_name.replace("Denny-", ""), book_name, skill_dirs)
    sha_meta = get_sha(repo_name, "_meta.json")
    print(f"    _meta.json: {write_upload_str(repo_name, meta_content, '_meta.json', sha_meta)}")

    # SKILL.md（meta入口）
    meta_skill_content = generate_meta_skill_md(repo_name, book_name, skill_dirs)
    sha_skill = get_sha(repo_name, "SKILL.md")
    print(f"    SKILL.md (meta): {write_upload_str(repo_name, meta_skill_content, 'SKILL.md', sha_skill)}")

    # LICENSE
    sha_license = get_sha(repo_name, "LICENSE")
    print(f"    LICENSE: {write_upload_str(repo_name, LICENSE_TEMPLATE, 'LICENSE', sha_license)}")

    # ── Post-sync required-file guard (fail-fast) ──
    # 缺失这些文件中的任何一个 → 脚本以非零退出码终止
    required_files = {
        "README.md":           "根目录说明（从 INDEX.md 自动生成，book-class 必填）",
        "SKILL.md":            "meta入口文件",
        "_meta.json":          "版本与 skill 清单",
        "references/INDEX.md": "技能索引",
    }
    missing = []
    for path, desc in required_files.items():
        if not get_sha(repo_name, path):
            missing.append(f"{path} ({desc})")
    if missing:
        print(f"\n\n❌ POST-SYNC CHECK FAILED — missing required files:")
        for m in missing:
            print(f"   • {m}")
        print(f"\nSync incomplete. Fix and re-run. "
              f"(Hint: For book-class repos, ensure INDEX.md exists at the source path.)")
        sys.exit(1)
    print(f"\n✅ Post-sync check passed ({len(required_files)}/{len(required_files)} files)")

    print(f"\n✅ {repo_name} sync complete ({len(skill_dirs)} skills)")

# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n快速使用：")
        print("  # 书籍拆解类（自动识别）")
        print("  python3 github-sync-skill.py ~/workspace/books/48-laws-of-power")
        print("")
        print("  # 独立工具类")
        print("  python3 github-sync-skill.py ~/workspace/skills/Denny-taotie --repo-name Denny-taotie")
        print("")
        print("  # 归档旧repo")
        print("  python3 github-sync-skill.py --archive-patterns Denny-48laws,Denny-WTFA --archive-note 'Merged'")
        sys.exit(0)

    # ── 全局 archive 模式 ──
    if sys.argv[1] == "--archive-patterns":
        patterns_str = sys.argv[2] if len(sys.argv) > 2 else ""
        note = sys.argv[3] if len(sys.argv) > 3 else ""
        patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
        if patterns:
            archive_patterns(patterns, note)
        sys.exit(0)

    base_path = sys.argv[1]
    if not os.path.exists(base_path):
        print(f"ERROR: 路径不存在: {base_path}")
        sys.exit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo-name")
    parser.add_argument("--description", default="")
    parser.add_argument("--book-name")
    parser.add_argument("--archive-patterns", default="")
    args, _ = parser.parse_known_args(sys.argv[2:])

    skill_type = classify_skill_type(base_path)
    book_slug = os.path.basename(os.path.normpath(base_path))
    book_name = args.book_name or book_slug

    if skill_type == "book":
        repo_name = args.repo_name or f"Denny-{book_slug}"
        description = args.description or f"从《{book_name}》蒸馏的 Skills — Denny-cangjie"

        if args.archive_patterns:
            patterns = [p.strip() for p in args.archive_patterns.split(",") if p.strip()]
            archive_patterns(patterns, f"Migrated to {repo_name}")

        sync_book_skills(base_path, repo_name, book_name, description)

    else:  # tool
        skill_name = args.repo_name or book_slug
        repo_name = args.repo_name or f"Denny-{skill_name}"
        description = args.description or f"{skill_name} — Denny-cangjie skill"

        if args.archive_patterns:
            patterns = [p.strip() for p in args.archive_patterns.split(",") if p.strip()]
            archive_patterns(patterns, f"Replaced by {repo_name}")

        sync_tool_skill(base_path, repo_name, skill_name, description)

if __name__ == "__main__":
    main()
