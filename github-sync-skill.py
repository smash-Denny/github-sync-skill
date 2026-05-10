#!/usr/bin/env python3
"""
skill-bump.py — Denny Skill 仓库版本 bump 唯一执行入口

用法:
    python3 skill-bump.py <repo_path> <version> [change_message] [--desc-file <path>]

示例:
    python3 skill-bump.py /path/to/skill v3.1.3 "修复XX问题"
    python3 skill-bump.py /path/to/skill v3.4.0 "漏斗升级" --desc-file /tmp/changes.md

注意:
    change_message 必须包含中文（纯英文将被拒绝执行）
    --desc-file 提供详细 CHANGELOG 描述（Markdown 格式，可选）

执行流程（原子化，不遗漏任何步骤）:
    1. 验证 repo_path 存在
    2. 解析 SKILL.md frontmatter（如有）
    3. 创建 versions/vX.X.X.md（变更说明）
    4. 创建 versions/vX.X.X-SKILL.md（SKILL.md 快照）
    5. 更新 CHANGELOG.md（版本表 + entry）
    6. 更新 README.md 版本号行（徽章/中文版本行，不碰版本历史区域）
    6.5. README 版本历史提醒（需手动维护或链接CHANGELOG）
    7. 更新 _meta.json version（如有）
    8. 更新 SKILL.md frontmatter version（如有）
    8.5. README 过时内容检测（扫描暂不支持/TODO等标记）
    9. git add -A
    10. git commit
    11. git push（最多3次重试，失败后自动 fallback 到 GitHub API）
    12. GitHub API 验证

验证通过标准: GitHub API 返回的 latest commit sha 与本地一致
"""

import sys
import os
import re
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _extract_token_from_remote(repo_path=None):
    """尝试从 git remote URL 提取 token（作为环境变量的 fallback）"""
    global GITHUB_TOKEN
    if GITHUB_TOKEN:
        return GITHUB_TOKEN
    if repo_path:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(repo_path), capture_output=True, text=True, timeout=5
            )
            url = result.stdout.strip()
            m = re.search(r"://[^:]+:([^@]+)@", url)
            if m:
                GITHUB_TOKEN = m.group(1)
                return GITHUB_TOKEN
        except Exception:
            pass
    return GITHUB_TOKEN
TZ_CST = timezone(timedelta(hours=8))

def log(msg, tag="INFO"):
    print(f"[{tag}] {msg}", flush=True)

def fatal(msg):
    print(f"[FATAL] {msg}", flush=True)
    sys.exit(1)

def run(cmd, cwd=None, check=True):
    """执行 shell 命令，失败则 fatal"""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True
    )
    if check and result.returncode != 0:
        fatal(f"命令失败: {cmd}\n  stderr: {result.stderr.strip()}")
    return result

def gh_api(url, repo_path=None, allow_failure=False):
    """GitHub API GET，返回 parsed JSON。allow_failure=True 时不 fatal。"""
    token = _extract_token_from_remote(repo_path)
    req = urllib.request.Request(
        f"https://api.github.com{url}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "skill-bump.py/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if allow_failure:
            return None
        fatal(f"GitHub API 失败 {url}: {e.code} {e.reason}")
    except Exception as e:
        if allow_failure:
            return None
        fatal(f"GitHub API 网络错误 {url}: {e}")

# ─────────────────────────────────────────────────────────
# 步骤 1: 验证 repo_path
# ─────────────────────────────────────────────────────────
def step1_validate_repo(repo_path):
    log("步骤1: 验证 repo_path")
    rp = Path(repo_path)
    if not rp.exists():
        fatal(f"repo_path 不存在: {repo_path}")
    if not (rp / ".git").exists():
        fatal(f"repo_path 不是 git 仓库: {repo_path}")
    log(f"  ✅ 仓库有效: {repo_path}")
    return rp

# ─────────────────────────────────────────────────────────
# 步骤 2: 解析 SKILL.md frontmatter
# ─────────────────────────────────────────────────────────
def step2_parse_frontmatter(repo_path):
    log("步骤2: 解析 SKILL.md frontmatter")
    skill_md = repo_path / "SKILL.md"
    if not skill_md.exists():
        log("  ⚠️  SKILL.md 不存在，跳过")
        return {}

    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        log("  ⚠️  SKILL.md 无 frontmatter，跳过")
        return {}

    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    log(f"  ✅ frontmatter 解析成功: {fm}")
    return fm

# ─────────────────────────────────────────────────────────
# 步骤 3: 创建 versions/vX.X.X.md
# ─────────────────────────────────────────────────────────
def step3_create_version_doc(repo_path, version, change_message):
    # version 已在 main() 中标准化为带 v 前缀
    log(f"步骤3: 创建 versions/{version}.md")
    versions_dir = repo_path / "versions"
    versions_dir.mkdir(exist_ok=True)

    today = datetime.now(TZ_CST).strftime("%Y-%m-%d")
    doc_path = versions_dir / f"{version}.md"

    # 查找上一个版本
    prev_ver = _find_previous_version(versions_dir, version)

    lines = [
        f"# {version}",
        "",
        f"> 发布日期：{today}",
        f"> 上一版本：{prev_ver}",
        "",
        "## 变更内容",
        "",
        f"{change_message}",
        "",
        "## 完整变更清单",
        "",
        f"详见 [CHANGELOG.md](../CHANGELOG.md) 中的 {version} 章节。",
        "",
    ]

    doc_path.write_text("\n".join(lines), encoding="utf-8")
    log(f"  ✅ 创建: {doc_path}")

def _find_previous_version(versions_dir, current_version):
    """在 versions/ 目录中找到当前版本的上一个版本"""
    cur_num = current_version.lstrip('v')
    cur_parts = tuple(int(x) for x in cur_num.split('.'))
    prev_parts = None
    prev_name = "无"
    for f in versions_dir.iterdir():
        if not f.name.endswith('.md') or f.name == 'CHANGELOG.md':
            continue
        m = re.match(r'v?(\d+\.\d+\.\d+)', f.name)
        if not m:
            continue
        parts = tuple(int(x) for x in m.group(1).split('.'))
        if parts < cur_parts:
            if prev_parts is None or parts > prev_parts:
                prev_parts = parts
                prev_name = f'v{m.group(1)}'
    return prev_name

# ─────────────────────────────────────────────────────────
# 步骤 4: 创建 versions/vX.X.X-SKILL.md 快照
# ─────────────────────────────────────────────────────────
def step4_snapshot_skill(repo_path, version):
    log(f"步骤4: 创建 SKILL.md 快照 versions/{version}-SKILL.md")
    skill_md = repo_path / "SKILL.md"
    if not skill_md.exists():
        log("  ⚠️  SKILL.md 不存在，跳过快照")
        return

    snapshot_path = repo_path / "versions" / f"{version}-SKILL.md"
    snapshot_path.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")
    log(f"  ✅ 快照: {snapshot_path}")


# 书籍拆解类：同时快照 skills/ 下所有 SKILL.md
    if (repo_path / "skills").is_dir():
        for skill_dir in sorted((repo_path / "skills").iterdir()):
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    snap = repo_path / "versions" / f"{version}-skill-{skill_dir.name}-SKILL.md"
                    snap.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")
                    log(f"  ✅ skill快照: {snap.name}")

# ─────────────────────────────────────────────────────────
# 步骤 5: 更新 CHANGELOG.md
# ─────────────────────────────────────────────────────────
def step5_update_changelog(repo_path, version, change_message, desc_content=None):
    # version 已在 main() 中标准化为带 v 前缀
    log(f"步骤5: 更新 CHANGELOG.md")
    cl_path = repo_path / "CHANGELOG.md"
    today = datetime.now(TZ_CST).strftime("%Y-%m-%d")

    if not cl_path.exists():
        new_section = f"## {version}（{today}\n\n{change_message}\n\n---\n"
        content = f"# Changelog\n\n{new_section}"
        cl_path.write_text(content, encoding="utf-8")
        log(f"  ✅ 新建 CHANGELOG.md")
        return

    text = cl_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ── 1. 在版本概览表格末尾插入新行 ──
    # 找到表格最后一行（以 | [v 或 | [V 开头）
    last_table_row = -1
    for i, line in enumerate(lines):
        if re.match(r"\|\s*\[?[vV]", line):
            last_table_row = i

    if last_table_row >= 0:
        ver_anchor = version.lstrip('v').replace('.', '')
        version_link = f"[{version}](#{ver_anchor})"
        new_row = f"| {version_link} | {today} | {change_message} |"
        lines.insert(last_table_row + 1, new_row)
        log(f"  ✅ 版本概览表新增行: {new_row[:60]}...")
    else:
        log("  ⚠️  CHANGELOG.md 未找到版本概览表格，跳过表格行插入")

    # ── 2. 在版本概览表格之后、第一个旧版本 section 之前插入新 section ──
    # P0 修复：之前找第一个 ## heading 插入，会插到表格上方。正确位置是表格结束后。
    # 策略：找到最后一个表格数据行（| [v 开头）之后，找第一个 ## heading，在它前面插入。
    insert_idx = None
    if last_table_row >= 0:
        # 从表格最后一行往后找第一个 ## heading
        for i in range(last_table_row + 1, len(lines)):
            if lines[i].startswith("## "):
                insert_idx = i
                break
        # 如果表格后面没有 ## heading（比如文件到头了），追加到末尾
        if insert_idx is None:
            insert_idx = len(lines)
    else:
        # 没找到表格，回退到旧逻辑：找第一个 ## heading
        for i, line in enumerate(lines):
            if line.startswith("## "):
                insert_idx = i
                break

    # 生成 section 内容：有详细描述文件就用，没有就用模板
    if desc_content:
        section_body = desc_content
    else:
        section_body = f"""{change_message}

### 核心变化

<!-- 请补充具体变化点 -->

### 影响范围

<!-- 请补充影响范围 -->"""

    new_section = f"""## {version}（{today}）

{section_body}

---"""

    if insert_idx is not None:
        lines.insert(insert_idx, "")
        lines.insert(insert_idx, new_section)
        log(f"  ✅ 新版本 section 插入到行 {insert_idx}")
    else:
        lines.append("")
        lines.append(new_section)
        log(f"  ✅ 新版本 section 追加到末尾")

    cl_path.write_text("\n".join(lines), encoding="utf-8")

# ─────────────────────────────────────────────────────────
# 步骤 6: 更新 README.md 版本号行（v1.2 简化版）
# ─────────────────────────────────────────────────────────
# 职责：只更新 README 中的「版本号行」和「版本徽章」。
# 不负责版本历史区域的追加（那是人维护的展示层，详见 CHANGELOG.md）。
# ─────────────────────────────────────────────────────────
def step6_update_readme(repo_path, version, change_message):
    log(f"步骤6: 更新 README.md 版本号行")
    rm_path = repo_path / "README.md"
    if not rm_path.exists():
        log("  ⚠️  README.md 不存在，跳过")
        return

    text = rm_path.read_text(encoding="utf-8")
    ver_num = version.lstrip('v')
    updated_any = False

    # 1. 更新版本徽章（如 Version-v3.1 → Version-v3.2）
    badge_m = re.search(r'Version-v[\d.]+', text)
    if badge_m:
        text = re.sub(r'Version-v[\d.]+', f'Version-v{ver_num}', text)
        log(f"  ✅ README.md 版本徽章更新 → v{ver_num}")
        updated_any = True

    # 2. 更新 Prev-v 版本徽章
    prev_m = re.search(r'Prev-v[\d.]+', text)
    if prev_m:
        text = re.sub(r'Prev-v[\d.]+', f'Prev-v{ver_num}', text)
        log(f"  ✅ README.md Prev徽章更新 → v{ver_num}")
        updated_any = True

    # 3. 更新中文版本行（如 **版本**：v2.4.0）
    cn_ver_m = re.search(r'(版本[^\n]*?[：:]\s*v)[\d.]+', text)
    if cn_ver_m:
        text = re.sub(r'(版本[^\n]*?[：:]\s*v)[\d.]+', rf'\g<1>{ver_num}', text)
        log(f"  ✅ README.md 中文版本行更新 → v{ver_num}")
        updated_any = True

    # 4. 更新英文 Version 行（如 **Version**: 1.2.0）
    en_ver_m = re.search(r'(Version[^\n]*?[：:]\s*v?)[\d.]+', text, re.IGNORECASE)
    if en_ver_m and not cn_ver_m:  # 避免和中文行冲突
        text = re.sub(r'(Version[^\n]*?[：:]\s*v?)[\d.]+', rf'\g<1>{ver_num}', text, flags=re.IGNORECASE)
        log(f"  ✅ README.md Version行更新 → v{ver_num}")
        updated_any = True

    if updated_any:
        rm_path.write_text(text, encoding="utf-8")

        # 写入后验证
        verify_text = rm_path.read_text(encoding="utf-8")
        version_found = False
        for pat in [rf'Version-v{re.escape(ver_num)}', rf'版本.*?v{re.escape(ver_num)}', rf'Version.*?{re.escape(ver_num)}']:
            if re.search(pat, verify_text, re.IGNORECASE):
                version_found = True
                break
        if not version_found:
            log(f"  ⚠️  写入后验证：未在 README 中找到 v{ver_num}，请手动检查")
    else:
        log("  ⚠️  README 中未找到可更新的版本号行（无徽章/版本行）")

    # 🟡4：自动在 README 版本历史表格末尾追加新行
    _readme_append_version_row(rm_path, version, change_message)

# ─────────────────────────────────────────────────────────
# 🟡4: 自动追加 README 版本历史表格行
# ─────────────────────────────────────────────────────────
def _readme_append_version_row(rm_path, version, change_message):
    """在 README.md 版本历史表格末尾追加新版本行（如果尚未存在）"""
    if not rm_path.exists():
        return
    text = rm_path.read_text(encoding="utf-8")
    ver_num = version.lstrip('v')

    # 检查是否已存在该版本行（避免重复追加）
    if re.search(rf'\|\s*\*\*\[?{re.escape(version)}', text) or re.search(rf'\|\s*\*\*\[?v?{re.escape(ver_num)}', text):
        log(f"  ℹ️  README 版本历史表格已包含 {version}，跳过追加")
        return

    # 找版本历史表格区域（## 版本历史 之后的 | ** 数据行）
    # 关键特征：版本历史表格的数据行以 | ** 开头（加粗版本号）
    # 遇到不以 | ** 开头但以 | 开头的行 = 离开了版本历史表格
    lines = text.splitlines()
    table_start = -1
    table_end = -1
    for i, line in enumerate(lines):
        if '版本历史' in line or 'Version History' in line:
            # 找到标题行，继续往下找表格
            for j in range(i + 1, len(lines)):
                if lines[j].startswith('| **'):
                    # 版本历史数据行
                    if table_start == -1:
                        table_start = j
                    table_end = j
                elif lines[j].startswith('|') and not lines[j].startswith('| **'):
                    # 表格分隔行或表头行，跳过但不终止
                    if table_start == -1 and ('版本' in lines[j] or 'Version' in lines[j] or '---' in lines[j] or '核心' in lines[j]):
                        continue  # 表头/分隔行，继续找数据行
                    elif table_start > 0:
                        break  # 已进入数据区，遇到非数据行 = 表格结束
                elif not lines[j].startswith('|') and lines[j].strip():
                    if table_start > 0:
                        break  # 非表格行 = 表格结束
                    # table_start 还没找到，继续找
            break

    if table_end < 0:
        log("  ⚠️  README 未找到版本历史表格，跳过自动追加")
        return

    # 生成新行：截断 change_message 到 50 字
    short_msg = change_message[:50] + ('...' if len(change_message) > 50 else '')
    new_row = f"| **[{version}](#{ver_num.replace('.', '')})** | {short_msg} |"

    # 版本历史表应为降序（最新在前），新版本应插入到所有现有行之前
    # 即：插入到 table_start 位置（第一个已有数据行之前）
    # 注意：不是 table_end+1（那是追加到末尾，会导致新版本出现在最底部）
    lines.insert(table_start, new_row)
    rm_path.write_text('\n'.join(lines), encoding="utf-8")
    log(f"  ✅ README 版本历史表格已插入最新版本（降序）: {version}")

# ─────────────────────────────────────────────────────────
# 步骤 7: 更新 _meta.json version
# ─────────────────────────────────────────────────────────
def step7_update_meta(repo_path, version):
    log(f"步骤7: 更新 _meta.json version")
    meta_path = repo_path / "_meta.json"
    if not meta_path.exists():
        log("  ⚠️  _meta.json 不存在，跳过")
        return

    try:
        raw = meta_path.read_text(encoding="utf-8")
        # 去掉 YAML frontmatter 包裹（饕餮的 _meta.json 用 --- 分隔）
        clean = re.sub(r'^---\n.*?\n---\n?', '', raw, flags=re.DOTALL)
        meta = json.loads(clean)
    except json.JSONDecodeError:
        log(f"  ⚠️  _meta.json 格式错误，跳过")
        return

    meta["version"] = version
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"  ✅ _meta.json version → {version}")

# ─────────────────────────────────────────────────────────
# 步骤 8: 更新 SKILL.md frontmatter version
# ─────────────────────────────────────────────────────────
def step8_update_skill_frontmatter(repo_path, version, is_book=False):
    log(f"步骤8: 更新 SKILL.md frontmatter version")
    skill_md = repo_path / "SKILL.md"
    if not skill_md.exists():
        log("  ⚠️  SKILL.md 不存在，跳过")
        return

    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---)", text, re.DOTALL)
    if not m:
        log("  ⚠️  SKILL.md 无 frontmatter，跳过")
        return

    fm_lines = m.group(2).splitlines()
    updated = False
    new_fm_lines = []
    for line in fm_lines:
        if re.match(r"^version:", line):
            new_fm_lines.append(f'version: "{version}"')
            updated = True
        else:
            new_fm_lines.append(line)

    if updated:
        new_text = m.group(1) + "\n".join(new_fm_lines) + m.group(3) + text[m.end():]
        skill_md.write_text(new_text, encoding="utf-8")
        log(f"  ✅ SKILL.md frontmatter version → {version}")
    else:
        log("  ⚠️  SKILL.md frontmatter 无 version 字段，跳过")
        return

    # 更新 SKILL.md 内容标题中的版本号
    text = skill_md.read_text(encoding="utf-8")
    end_fm = text.find("---", 3)
    if end_fm > 0:
        content = text[end_fm + 3:]
        title_match = re.search(r"^(# .+?)\s+v?\d+\.\d+(\.\d+)?", content, re.MULTILINE)
        if title_match:
            old_title = title_match.group(0)
            prefix = title_match.group(1)
            new_title = f"{prefix} {version}"
            text = text.replace(old_title, new_title, 1)
            skill_md.write_text(text, encoding="utf-8")
            log(f"  ✅ SKILL.md 内容标题版本号 → {version}")
        else:
            log("  ℹ️  SKILL.md 内容标题无版本号标记，跳过")

# ─────────────────────────────────────────────────────────
# 步骤 8.5: README 过时内容检测
# ─────────────────────────────────────────────────────────
def step85_check_readme_stale(repo_path, version):
    """扫描 README.md 中可能过时的措辞，提醒开发者检查"""
    log("步骤8.5: README 过时内容检测")
    rm_path = repo_path / "README.md"
    if not rm_path.exists():
        log("  ⚠️  README.md 不存在，跳过")
        return

    text = rm_path.read_text(encoding="utf-8")
    stale_markers = [
        r'暂不支持', r'暂不计入', r'暂未实现', r'TODO', r'todo', r'FIXME', r'fixme',
        r'待修复', r'待更新', r'待完善',
    ]
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat in stale_markers:
            if re.search(pat, line):
                found.append((i, line.strip()))
                break

    if found:
        log(f"  ⚠️  README.md 发现 {len(found)} 处可能过时的内容，请检查是否已在 v{version} 修复：")
        for ln, content in found[:5]:
            log(f"    L{ln}: {content[:80]}")
        if len(found) > 5:
            log(f"    ... 共 {len(found)} 处")
    else:
        log("  ✅ README.md 未发现过时标记")

# ─────────────────────────────────────────────────────────
# 🟢7: 检查 versions/ 目录异常
# ─────────────────────────────────────────────────────────
def step85b_check_versions_dir(repo_path, version):
    """检查 versions/ 目录是否有异常文件"""
    log("步骤8.7: versions/ 目录检查")
    versions_dir = repo_path / "versions"
    if not versions_dir.exists():
        log("  ⚠️  versions/ 目录不存在，跳过")
        return

    issues = []
    for f in versions_dir.iterdir():
        name = f.name
        # 检查1：裸版本号文件名（不带v前缀的 X.X.X.md）
        if re.match(r'\d+\.\d+\.\d+', name):
            issues.append(f"裸版本号文件名（缺v前缀）: {name}")
        # 检查2：CHANGELOG.md 不应存在于 versions/ 下
        if name == 'CHANGELOG.md':
            issues.append(f"versions/CHANGELOG.md 存在（应删除或改为根目录链接）: {name}")

    if issues:
        log(f"  ⚠️  versions/ 目录发现 {len(issues)} 个问题：")
        for issue in issues:
            log(f"    - {issue}")
    else:
        log("  ✅ versions/ 目录检查通过")

# ─────────────────────────────────────────────────────────
# 步骤 9-11: git add → commit → push
# ─────────────────────────────────────────────────────────
def step9_git_operations(repo_path, version, change_message):
    log("步骤9-11: git add → commit → push")
    rp = str(repo_path)

    # git config
    run("git config --global user.email || true", cwd=rp, check=False)
    run('git config --global user.name || true', cwd=rp, check=False)

    # 确保 remote 正确
    remotes = run("git remote -v", cwd=rp, check=False).stdout
    if "smash-Denny" not in remotes and "x-access-token" not in remotes:
        # 尝试修复
        try:
            remote_url = run("git remote get-url origin", cwd=rp, check=False).stdout.strip()
            if "smash-Denny" in remote_url or "github.com" in remote_url:
                new_url = remote_url.replace(
                    "https://github.com/",
                    f"https://x-access-token:{GITHUB_TOKEN}@github.com/"
                )
                run(f"git remote set-url origin {new_url}", cwd=rp)
                log(f"  ✅ remote 已配置 token")
        except:
            pass

    # git add
    run("git add -A", cwd=rp)

    # 检查是否有变更
    status = run("git status --short", cwd=rp, check=False).stdout
    if not status.strip():
        log("  ⚠️  没有文件变更（可能所有文件已是最新的）")
        return False

    log(f"  📄 变更文件:\n{status}")

    # ── commit 前全面一致性验证 ──
    ver_num = version.lstrip('v')
    checks = []

    # 检查 _meta.json
    meta_path = repo_path / "_meta.json"
    if meta_path.exists():
        try:
            raw = meta_path.read_text(encoding="utf-8")
            clean = re.sub(r'^---\n.*?\n---\n?', '', raw, flags=re.DOTALL)
            meta = json.loads(clean)
            meta_ver = str(meta.get('version', ''))
            # 必须带 v 前缀
            if meta_ver == version:
                checks.append(("_meta.json", True, f"{version}"))
            elif meta_ver == ver_num:
                checks.append(("_meta.json", False, f"版本号缺少 v 前缀：{meta_ver}，期望 {version}"))
            else:
                checks.append(("_meta.json", False, f"期望 {version}，实际 {meta_ver}"))
        except Exception as e:
            checks.append(("_meta.json", False, f"读取失败: {e}"))

    # 检查 SKILL.md frontmatter
    skill_path = repo_path / "SKILL.md"
    if skill_path.exists():
        skill_text = skill_path.read_text(encoding="utf-8")
        fm_m = re.match(r'^---\n(.*?)\n---', skill_text, re.DOTALL)
        if fm_m:
            fm_ver_m = re.search(r'^version:\s*["\']?(v?[\d.]+)', fm_m.group(1), re.M)
            if fm_ver_m and fm_ver_m.group(1) == version:
                checks.append(("SKILL.md version", True, f"{version}"))
            elif fm_ver_m:
                checks.append(("SKILL.md version", False, f"期望 {version}，实际 {fm_ver_m.group(1)}"))
            else:
                checks.append(("SKILL.md version", None, "无 version 字段"))

        # 检查 SKILL.md 标题包含正确版本号
        title_m = re.search(r'^# .+?\s+v?\d+\.\d+(\.\d+)?', skill_text, re.MULTILINE)
        if title_m:
            if version in title_m.group(0):
                checks.append(("SKILL.md 标题", True, f"包含 {version}"))
            elif ver_num in title_m.group(0):
                checks.append(("SKILL.md 标题", False, f"版本号缺少 v 前缀：标题为 '{title_m.group(0).strip()}'"))
            else:
                checks.append(("SKILL.md 标题", None, f"版本号不匹配：{title_m.group(0).strip()}"))
        else:
            checks.append(("SKILL.md 标题", None, "无版本号标题行"))

    # 检查 versions/vX.X.X.md 存在
    ver_doc = repo_path / "versions" / f"{version}.md"
    if ver_doc.exists():
        checks.append(("versions/文档", True, f"{version}.md 存在"))
    else:
        checks.append(("versions/文档", False, f"{version}.md 不存在"))

    # 检查 CHANGELOG 包含新版本（表格行 + section）
    cl_path = repo_path / "CHANGELOG.md"
    if cl_path.exists():
        cl_text = cl_path.read_text(encoding="utf-8")
        # 检查是否存在版本概览表格（以 | [v 开头的行）
        has_version_table = bool(re.search(r'\|\s*\[v', cl_text))
        if has_version_table:
            # 检查表格行
            table_row_m = re.search(rf'\|\s*\[{re.escape(version)}\]', cl_text)
            if table_row_m:
                checks.append(("CHANGELOG 表格", True, f"包含 [{version}] 链接"))
            else:
                # 检查是否只有裸版本号（缺v）
                bare_m = re.search(rf'\|\s*\[?{re.escape(ver_num)}\]?', cl_text)
                if bare_m:
                    checks.append(("CHANGELOG 表格", False, f"版本号缺 v 前缀或链接格式错误"))
                else:
                    checks.append(("CHANGELOG 表格", False, f"未找到 {version}"))
        else:
            checks.append(("CHANGELOG 表格", None, "无版本概览表格（跳过）"))
        # 检查 section 标题
        section_m = re.search(rf'^## {re.escape(version)}', cl_text, re.MULTILINE)
        if section_m:
            checks.append(("CHANGELOG section", True, f"## {version}"))
        else:
            bare_section = re.search(rf'^## {re.escape(ver_num)}', cl_text, re.MULTILINE)
            if bare_section:
                checks.append(("CHANGELOG section", False, f"section 标题缺 v 前缀：## {ver_num}"))
            else:
                checks.append(("CHANGELOG section", False, f"未找到 ## {version}"))

    # 检查 versions/ 下无裸版本号文件名（不带v的X.X.X.md）
    versions_dir = repo_path / "versions"
    if versions_dir.exists():
        bare_files = [f.name for f in versions_dir.iterdir()
                      if re.match(r'\d+\.\d+\.\d+', f.name)]
        if bare_files:
            checks.append(("versions/ 文件名", False, f"发现裸版本号文件：{', '.join(bare_files)}"))
        else:
            checks.append(("versions/ 文件名", True, "所有版本文件名均带 v 前缀"))

    # 输出验证结果
    has_fail = any(not c[1] for c in checks if c[1] is not None)
    if has_fail:
        log("  ❌ commit 前验证失败：")
        for name, ok, detail in checks:
            tag = "✅" if ok else ("⚠️" if ok is None else "❌")
            log(f"    {tag} {name}: {detail}")
        fatal("  验证不通过，请修复后重新运行 skill-bump")
    else:
        log("  ✅ commit 前验证通过：")
        for name, ok, detail in checks:
            if ok is not None:
                log(f"    ✅ {name}: {detail}")

    # git commit
    commit_msg = f"bump: {version} — {change_message}"
    run(f'git commit -m "{commit_msg}"', cwd=rp)
    log(f"  ✅ git commit: {commit_msg}")

    # git push（带重试）
    log("  正在 push...")
    push_ok = False
    for attempt in range(1, 4):  # 最多3次
        push_result = run("git push 2>&1", cwd=rp, check=False)
        if push_result.returncode == 0:
            push_ok = True
            break
        # 尝试带 token 的 push（仅第一次）
        if attempt == 1:
            remote_url = run("git remote get-url origin", cwd=rp, check=False).stdout.strip()
            if "x-access-token" not in remote_url and "smash-Denny" in remote_url:
                new_url = remote_url.replace(
                    "https://github.com/",
                    f"https://x-access-token:{GITHUB_TOKEN}@github.com/"
                )
                run(f"git remote set-url origin {new_url}", cwd=rp)
                continue
        if attempt < 3:
            import time
            log(f"  ⚠️  push 失败（第{attempt}次），5秒后重试...")
            time.sleep(5)

    if not push_ok:
        log(f"  ⚠️  git push 3次重试均失败，切换到 GitHub API 推送...")
        api_ok = _push_via_github_api(repo_path, version, change_message)
        if not api_ok:
            fatal(f"  ❌ git push + GitHub API 均失败")
        log(f"  ✅ GitHub API 推送成功")
        return True

    log(f"  ✅ git push 成功")
    return True

# ─────────────────────────────────────────────────────────
# GitHub API push fallback（git push超时时的后备方案）
# ─────────────────────────────────────────────────────────
def _push_via_github_api(repo_path, version, change_message):
    """git push 失败后，通过 GitHub Contents API 逐文件推送"""
    import time as _time

    rp = Path(repo_path)
    token = _extract_token_from_remote(rp)
    if not token:
        log("  ❌ 无 GitHub Token，无法使用 API fallback")
        return False

    # 提取 owner/repo
    remote_url = run("git remote get-url origin", cwd=str(rp), check=False).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote_url)
    if not m:
        log(f"  ❌ 无法解析 remote URL: {remote_url}")
        return False
    owner, repo_name = m.group(1), m.group(2)

    # 获取已 commit 的文件列表
    # 对比 HEAD~1 和 HEAD 的差异
    diff_result = run("git diff --name-only HEAD~1 HEAD", cwd=str(rp), check=False)
    if diff_result.returncode != 0 or not diff_result.stdout.strip():
        # 可能只有一个commit，用 git show
        diff_result = run("git show --name-only --pretty=format: HEAD", cwd=str(rp), check=False)
    changed_files = [f for f in diff_result.stdout.strip().splitlines() if f.strip()]

    if not changed_files:
        log("  ⚠️  无变更文件")
        return False

    log(f"  📋 准备通过 API 推送 {len(changed_files)} 个文件...")

    all_ok = True
    for filepath in changed_files:
        local_file = rp / filepath
        if not local_file.exists():
            # 文件被删除了，通过 API 删除
            log(f"  ⚠️  跳过已删除文件: {filepath}")
            continue

        # 获取远程文件的 SHA（如果存在）
        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filepath}"
        req = urllib.request.Request(api_url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "skill-bump.py/1.0",
        })
        remote_sha = None
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                remote_data = json.loads(resp.read())
                remote_sha = remote_data.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                remote_sha = None  # 新文件
            else:
                log(f"  ⚠️  获取 {filepath} SHA 失败: {e.code}")
                all_ok = False
                continue
        except Exception:
            log(f"  ⚠️  获取 {filepath} SHA 超时")
            all_ok = False
            continue

        # 读取并 base64 编码
        import base64
        content_b64 = base64.b64encode(local_file.read_bytes()).decode()

        # PUT 推送
        payload = json.dumps({
            "message": f"bump: {version} — {change_message} (API push)",
            "content": content_b64,
            **({"sha": remote_sha} if remote_sha else {})
        }).encode()

        req2 = urllib.request.Request(api_url, data=payload, method="PUT", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "skill-bump.py/1.0",
        })
        try:
            with urllib.request.urlopen(req2, timeout=15) as resp:
                result = json.loads(resp.read())
                log(f"  ✅ {filepath}: {result['commit']['sha'][:8]}")
        except urllib.error.HTTPError as e:
            body = json.loads(e.read()) if e.headers.get('content-type','').startswith('application/json') else {}
            log(f"  ❌ {filepath}: {e.code} {body.get('message','')[:60]}")
            all_ok = False
        except Exception as e:
            log(f"  ❌ {filepath}: {e}")
            all_ok = False

    return all_ok

# ─────────────────────────────────────────────────────────
# 步骤 12: GitHub API 验证
# ─────────────────────────────────────────────────────────
def step12_verify(repo_path):
    log("步骤12: GitHub API 验证（commit SHA + 远程内容）")
    rp = Path(repo_path)

    # 从 remote URL 提取 owner/repo
    remote_url = run("git remote get-url origin", cwd=str(rp), check=False).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote_url)
    if not m:
        log(f"  ⚠️  无法从 remote URL 提取 owner/repo: {remote_url}，跳过验证")
        return

    owner, repo_name = m.group(1), m.group(2).rstrip(".git")
    token = _extract_token_from_remote(rp)

    # ── 第一部分：commit SHA 验证 ──
    data = gh_api(f"/repos/{owner}/{repo_name}/commits?per_page=1&sha=main", repo_path, allow_failure=True)
    if data is None:
        log(f"  ⚠️  GitHub API 验证失败（可能是 token 权限问题），但 push 已成功")
        log(f"  ⚠️  建议手动确认: https://github.com/{owner}/{repo_name}/commits")
        return
    try:
        if data and isinstance(data, list):
            sha = data[0]["sha"][:8]
            local_sha = run("git rev-parse HEAD", cwd=str(rp), check=False).stdout.strip()[:8]
            if sha == local_sha:
                log(f"  ✅ commit {sha} 已在线")
            else:
                log(f"  ⚠️  GitHub SHA ({sha}) ≠ 本地 SHA ({local_sha})，请手动确认")
    except Exception as e:
        log(f"  ⚠️  commit 验证异常: {e}")

    # ── 第二部分：🔴3 远程内容验证 ──
    log("  📋 远程内容验证...")
    remote_checks = []

    import base64 as _b64

    def _read_remote_file(path):
        """读取 GitHub 远程文件内容，返回 str 或 None"""
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "skill-bump.py/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode())
                return _b64.b64decode(d['content']).decode('utf-8')
        except Exception:
            return None

    def _list_remote_dir(path):
        """列出 GitHub 远程目录，返回 [name, ...] 或 None"""
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "skill-bump.py/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode())
                return [f['name'] for f in d] if isinstance(d, list) else None
        except Exception:
            return None

    # 获取当前 bump 的版本号
    ver_num = ''
    # 从 _meta.json 获取版本号
    meta_path = rp / "_meta.json"
    if meta_path.exists():
        try:
            raw = meta_path.read_text(encoding="utf-8")
            clean = re.sub(r'^---\n.*?\n---\n?', '', raw, flags=re.DOTALL)
            meta = json.loads(clean)
            ver_num = str(meta.get('version', '')).lstrip('v')
        except Exception:
            pass
    if not ver_num:
        log("  ⚠️  无法确定版本号，跳过远程内容验证")
        return

    # 验证1：CHANGELOG.md 内容
    cl_content = _read_remote_file("CHANGELOG.md")
    if cl_content:
        # 表格行包含当前版本（仅当存在版本概览表格时检查）
        has_version_table = bool(re.search(r'\|\s*\[v', cl_content))
        if has_version_table:
            if re.search(rf'\|\s*\[v{re.escape(ver_num)}\]', cl_content):
                remote_checks.append(("CHANGELOG 表格", True, f"包含 v{ver_num}"))
            else:
                remote_checks.append(("CHANGELOG 表格", False, f"未找到 v{ver_num}"))
        else:
            remote_checks.append(("CHANGELOG 表格", None, "无版本概览表格（跳过）"))
        # section 标题
        if re.search(rf'^## v{re.escape(ver_num)}', cl_content, re.MULTILINE):
            remote_checks.append(("CHANGELOG section", True, f"## v{ver_num}"))
            # 🟢P2：检查 section 位置是否在表格下方
            cl_lines = cl_content.split('\n')
            table_last_row = -1
            section_line = -1
            for i, line in enumerate(cl_lines):
                if re.match(r'\|\s*\[v', line):
                    table_last_row = i
                if line.startswith(f'## v{ver_num}'):
                    section_line = i
            if table_last_row >= 0 and section_line >= 0:
                if section_line > table_last_row:
                    remote_checks.append(("CHANGELOG section位置", True, f"在表格下方（{section_line} > {table_last_row}）"))
                else:
                    remote_checks.append(("CHANGELOG section位置", False, f"在表格上方！（{section_line} < {table_last_row}）需修复"))
            # 检查 section 描述长度
            section_start = -1
            section_end = -1
            for i, line in enumerate(cl_lines):
                if line.startswith(f'## v{ver_num}'):
                    section_start = i
                elif section_start >= 0 and line.startswith('## v') and i > section_start:
                    section_end = i
                    break
            if section_start >= 0:
                section_text = '\n'.join(cl_lines[section_start:section_end if section_end > 0 else len(cl_lines)])
                # 统计非空非标题行数
                content_lines = [l for l in section_text.split('\n') if l.strip() and not l.startswith('#') and not l.startswith('---') and not l.startswith('|')]
                if len(content_lines) < 3:
                    remote_checks.append(("CHANGELOG 描述长度", False, f"section 只有 {len(content_lines)} 行内容，可能过于简略"))
                else:
                    remote_checks.append(("CHANGELOG 描述长度", True, f"section 有 {len(content_lines)} 行内容"))
        else:
            remote_checks.append(("CHANGELOG section", False, f"未找到 ## v{ver_num}"))
    else:
        remote_checks.append(("CHANGELOG.md", None, "无法读取远程文件"))

    # 验证2：README.md 内容
    rm_content = _read_remote_file("README.md")
    if rm_content:
        if re.search(rf'v{re.escape(ver_num)}', rm_content):
            remote_checks.append(("README 版本号", True, f"包含 v{ver_num}"))
        else:
            remote_checks.append(("README 版本号", False, f"未找到 v{ver_num}"))
    else:
        remote_checks.append(("README.md", None, "无法读取远程文件"))

    # 验证3：versions/ 目录
    versions_files = _list_remote_dir("versions")
    if versions_files is not None:
        # 检查无裸版本号文件名
        bare = [n for n in versions_files if re.match(r'\d+\.\d+\.\d+', n)]
        if bare:
            remote_checks.append(("versions/ 文件名", False, f"裸版本号: {', '.join(bare)}"))
        else:
            remote_checks.append(("versions/ 文件名", True, "全部带 v 前缀"))
        # 检查无 CHANGELOG.md
        if 'CHANGELOG.md' in versions_files:
            remote_checks.append(("versions/CHANGELOG", False, "存在（应删除）"))
        else:
            remote_checks.append(("versions/CHANGELOG", True, "不存在（正确）"))
    else:
        remote_checks.append(("versions/ 目录", None, "无法读取"))

    # 输出验证结果
    has_fail = any(not c[1] for c in remote_checks if c[1] is not None)
    if has_fail:
        log("  ⚠️  远程内容验证发现问题：")
        for name, ok, detail in remote_checks:
            tag = "✅" if ok else ("⚠️" if ok is None else "❌")
            log(f"    {tag} {name}: {detail}")
        log("  ⚠️  push 已成功但远程内容不一致，请手动确认")
    else:
        log("  ✅ 远程内容验证通过：")
        for name, ok, detail in remote_checks:
            if ok is not None:
                log(f"    ✅ {name}: {detail}")

def step13_sync_checker(repo_path):
    """
    步骤13: 内容完整性校验（skill-sync-checker）
    bump push 成功后执行，校验内容一致性，不一致则 FAIL。
    这是 skill-bump 的 post-flight check，确保版本号同步+内容完整。

    优先调用独立的 skill-sync-checker 模块；导入失败时使用内嵌 fallback。
    """
    log("步骤13: skill-sync-checker 内容完整性校验")

    # ── 尝试调用独立 sync-checker 模块 ──
    try:
        from sync_check import sync_check as _sc, format_result as _fr
        result = _sc(str(repo_path))
        for name, ok, detail in result["checks"]:
            tag = "PASS" if ok is True else "FAIL" if ok is False else "WARN"
            icon = "✅" if ok is True else "❌" if ok is False else "⚠️ "
            log(f"  {icon} {name}: {detail}")
        failed = [(n, d) for n, ok, d in result["checks"] if ok is False]
        log("")
        if failed:
            log(f"  ⚠️  sync-checker 发现 {len(failed)} 项问题，请修正后重新 bump")
            log(f"  ⚠️  bump push 已成功，但内容完整性未通过")
            return False
        else:
            log(f"  ✅ sync-checker 全部通过（{result['passed_count']} 项）")
            return True
    except ImportError:
        log("  [fallback] 独立模块未找到，使用内嵌校验逻辑")
        pass  # 继续使用内嵌逻辑
    except Exception as e:
        log(f"  [fallback] 独立模块调用失败（{e}），继续内嵌逻辑")
        pass

    # ── 内嵌 fallback 校验逻辑 ──
    rp = Path(repo_path)
    checks = []  # (name, passed, detail)

    # ── 读取关键文件 ──
    skill_md_text = (rp / "SKILL.md").read_text(encoding="utf-8") if (rp / "SKILL.md").exists() else ""
    changelog_text = (rp / "CHANGELOG.md").read_text(encoding="utf-8") if (rp / "CHANGELOG.md").exists() else ""
    readme_text = (rp / "README.md").read_text(encoding="utf-8") if (rp / "README.md").exists() else ""
    meta_text = (rp / "_meta.json").read_text(encoding="utf-8") if (rp / "_meta.json").exists() else ""
    versions_dir = rp / "versions"

    # 解析 frontmatter version
    fm_ver = ""
    m = re.match(r"^---\n(.*?)\n---", skill_md_text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("version:"):
                fm_ver = line.split(":", 1)[1].strip().strip('"').strip("'").lstrip("v")

    # 解析 _meta.json version
    meta_ver = ""
    try:
        meta = json.loads(meta_text)
        meta_ver = str(meta.get("version", "")).lstrip("v")
    except Exception:
        pass

    # CHANGELOG 第一个 ## vX.X.X 条目标题
    cl_first_ver = ""
    for line in changelog_text.splitlines():
        mm = re.match(r"^## v([0-9.]+)", line)
        if mm:
            cl_first_ver = mm.group(1)
            break

    # CHANGELOG 占位符检查（只检测真正的注释标记，不误判解释性文字）
    placeholder_issues = []
    for i, line in enumerate(changelog_text.splitlines(), 1):
        stripped = line.strip()
        # 只检测 HTML 注释标记 <!-- ... --> 或以注释格式出现的待填内容
        # 不检测解释性文字（如"CHANGELOG 无占位符"中的关键词）
        if re.search(r'<\!\-\-', stripped):  # HTML 注释 <!-- ... -->
            placeholder_issues.append(f"L{i}: {stripped[:60]}")
        # 检测显式的待填内容行（仅占位符文本，无实质内容）
        elif stripped and all(c in '请填写占位待补充TODO明说' for c in stripped):
            placeholder_issues.append(f"L{i}: {stripped[:60]}")

    # README 版本历史第一条版本号
    # 从 README 的"版本历史"表格中提取第一个真实版本号
    # 进入条件：行含"版本历史"（表头行）或前一行含"版本历史"（下一行就是表头或数据）
    readme_first_ver = ""
    prev_line_has_heading = False
    in_table_section = False
    for line in readme_text.splitlines():
        stripped = line.strip()
        # 进入版本历史表格区
        in_table_section = prev_line_has_heading or in_table_section
        prev_line_has_heading = '版本历史' in stripped and '|' not in stripped and not stripped.startswith('|')
        if not in_table_section:
            continue
        # 跳过表头行和分隔线（进入表格区后首行可能是表头）
        if re.match(r'^\|\s*[-:]+[-:\s]*\|', stripped):
            continue
        # 提取语义版本号 vX.X.X（在表格数据行中）
        if '|' in stripped and re.search(r'v\d+\.\d+\.\d+', stripped):
            vm = re.search(r'v\d+\.\d+\.\d+', stripped)
            readme_first_ver = vm.group(0).lstrip('v')
            break

    # versions/ 目录文件
    versions_files = list(versions_dir.iterdir()) if versions_dir.exists() else []
    versions_file_names = [f.name for f in versions_files]

    # versions/v{ver}.md 是否存在且非空
    def _ver_md_ok(ver):
        path = versions_dir / f"v{ver}.md"
        if not path.exists():
            return False, f"不存在: v{ver}.md"
        lines = path.read_text(encoding="utf-8").splitlines()
        content_lines = [l for l in lines if l.strip() and not l.startswith("#")]
        if len(content_lines) < 3:
            return False, f"v{ver}.md 空洞（仅 {len(content_lines)} 行实质内容）"
        return True, f"v{ver}.md OK ({len(content_lines)} 行实质内容)"

    # CHANGELOG 条目数
    cl_entries = len(re.findall(r"^## v[0-9.]+", changelog_text, re.MULTILINE))

    # ── Phase 1: 版本号一致性 ──
    log("  📋 Phase 1: 版本号一致性")
    if fm_ver and meta_ver and fm_ver != meta_ver:
        checks.append(("frontmatter vs _meta.json", False,
                        f"frontmatter={fm_ver}, _meta.json={meta_ver}"))
    else:
        checks.append(("frontmatter vs _meta.json", True, f"一致={fm_ver or meta_ver}"))

    if cl_first_ver and meta_ver and cl_first_ver != meta_ver:
        checks.append(("CHANGELOG首条 vs _meta.json", False,
                        f"CHANGELOG首条={cl_first_ver}, _meta.json={meta_ver}"))
    else:
        checks.append(("CHANGELOG首条 vs _meta.json", True,
                        f"一致={cl_first_ver or meta_ver}"))

    if readme_first_ver and cl_first_ver and readme_first_ver != cl_first_ver:
        checks.append(("README首条 vs CHANGELOG首条", False,
                        f"README首条={readme_first_ver}, CHANGELOG首条={cl_first_ver}"))
    else:
        checks.append(("README首条 vs CHANGELOG首条", True,
                        f"一致={readme_first_ver or cl_first_ver}"))

    # README 版本历史顺序（第一条应为最新版本）
    if readme_first_ver and cl_first_ver and readme_first_ver != cl_first_ver:
        checks.append(("README版本顺序", False,
                        f"最新={readme_first_ver}，应为={cl_first_ver}"))
    else:
        checks.append(("README版本顺序", True, f"最新={readme_first_ver or cl_first_ver}（降序正确）"))

    # ── Phase 2: 内容完整性 ──
    log("  📋 Phase 2: 内容完整性")
    if placeholder_issues:
        checks.append(("CHANGELOG占位符", False,
                        f"发现 {len(placeholder_issues)} 处: {'; '.join(placeholder_issues[:3])}"))
    else:
        checks.append(("CHANGELOG占位符", True, "无占位符残留"))

    ok_ver, detail_ver = _ver_md_ok(meta_ver)
    checks.append((f"versions/v{meta_ver}.md", ok_ver, detail_ver))

    if skill_md_text:  # SKILL类仓库才检查SKILL快照
        skill_snapshot = f"v{meta_ver}-SKILL.md"
        if skill_snapshot in versions_file_names:
            lines = (versions_dir / skill_snapshot).read_text(encoding="utf-8").splitlines()
            content_lines = [l for l in lines if l.strip() and not l.startswith("#")]
            if len(content_lines) < 3:
                checks.append((f"versions/{skill_snapshot}", False,
                                f"空洞（{len(content_lines)} 行实质内容）"))
            else:
                checks.append((f"versions/{skill_snapshot}", True,
                                f"OK（{len(content_lines)} 行实质内容）"))
        else:
            checks.append((f"versions/{skill_snapshot}", False, "文件不存在！"))

    # versions/ 文件数 vs CHANGELOG 条目数
    snapshot_count = len([n for n in versions_file_names if re.match(r'v[0-9.]+\.md$', n)])
    if cl_entries > 0 and snapshot_count < cl_entries:
        checks.append(("versions/快照数 vs CHANGELOG条目数", False,
                        f"快照={snapshot_count}, CHANGELOG条目={cl_entries}（缺 {cl_entries - snapshot_count} 个）"))
    elif cl_entries > 0:
        checks.append(("versions/快照数 vs CHANGELOG条目数", True,
                        f"快照={snapshot_count}, CHANGELOG条目={cl_entries}"))

    # ── Phase 3: README vs SKILL.md 架构一致性（基础检查） ──
    log("  📋 Phase 3: README vs SKILL.md 架构一致性（基础）")
    # 统计 README 中声称的"来源/组件"数量 vs SKILL.md SourceRegistry 中的数量
    readme_sources = set()
    sk_sk_sources = set()
    # 扫描 README 中的来源关键词
    for kw in ["Standard Ebooks", "Gutenberg", "Anna's Archive", "AnnaArchive"]:
        if kw in readme_text:
            readme_sources.add(kw)
    # 扫描 SKILL.md SourceRegistry 架构图中的来源
    # 架构图第一行格式: "SourceRegistry  ← 全局注册表"（含←箭头，无框线）
    # 子节点格式: "  ├── XxxSource  (...)"
    in_arch = False
    for i, line in enumerate(skill_md_text.splitlines()):
        stripped = line.rstrip()
        # 进入架构区：SourceRegistry + ← 箭头
        if "SourceRegistry" in stripped and ("←" in stripped or "<-" in stripped):
            in_arch = True
            continue
        # 退出架构区：碰到新的顶层标题（## 或 #）
        if in_arch and stripped.startswith("#"):
            in_arch = False
        if in_arch:
            for kw in ["StandardEbooksSource", "GutenbergSource", "AnnaArchiveSource"]:
                if kw in stripped:
                    sk_sk_sources.add(kw)
                    break

    # 简单检查：README 声称有 SE，但 SKILL.md 架构图没有
    if "Standard Ebooks" in readme_sources:
        if "StandardEbooks" not in "".join(sk_sk_sources):
            checks.append(("SE文档一致性", False,
                            "README描述了SE但SKILL.md架构树未列出StandardEbooksSource"))
        else:
            checks.append(("SE文档一致性", True, "README与SKILL.md均含SE"))

    # 检查 README 中是否有架构描述但内容过期
    if skill_md_text and changelog_text:
        # 如果 CHANGELOG 最新条目提到某关键词，但 README 里没有 → 警告
        cl_first_section = ""
        sec_start = -1
        cl_lines = changelog_text.splitlines()
        for i, line in enumerate(cl_lines):
            if re.match(rf"^## v{cl_first_ver or meta_ver}", line):
                sec_start = i
                break
        if sec_start >= 0:
            for i in range(sec_start + 1, len(cl_lines)):
                if cl_lines[i].startswith("## v"):
                    break
                cl_first_section += cl_lines[i] + "\n"
        # 检查关键功能词是否在 README 里
        for kw in ["Standard Ebooks", "三层来源", "download_priority", "pdf_quality"]:
            if kw in cl_first_section and kw.lower() not in readme_text.lower():
                checks.append(("README遗漏新功能", False,
                                f"CHANGELOG提到「{kw}」但README未提及"))
                break
        else:
            if cl_first_section.strip():
                checks.append(("README内容同步", True, "README与CHANGELOG新功能描述基本一致"))

    # ── Phase 3.5: SKILL.md 描述的文件 vs 代码实际存在性 ──
    log("  📋 Phase 3.5: SKILL.md 描述文件 vs 代码实际存在性")
    # 从 SKILL.md 和 README 中提取提及的工具文件名（如 pdf_quality.py, book_search.py）
    # 验证这些文件是否真实存在于 _tools/ 目录
    tools_dir = repo_path / "_tools"
    mentioned_files = set()
    if tools_dir.exists():
        # 提取 SKILL.md 中提及的 _tools/ 文件名（格式：`_tools/xxx.py` 或 `xxx.py`）
        combined_text = skill_md_text + "\n" + readme_text
        for fname in re.findall(r'_tools/([a-zA-Z_][a-zA-Z0-9_]*\.py)', combined_text):
            mentioned_files.add(fname)
        # 提取以代码块形式出现的文件名
        for fname in re.findall(r'`([a-zA-Z_][a-zA-Z0-9_]*\.py)`', combined_text):
            mentioned_files.add(fname)

        actual_files = {f.name for f in tools_dir.iterdir() if f.is_file() and f.suffix == '.py'}

        missing_files = []
        extra_described = []
        for fname in mentioned_files:
            if fname not in actual_files and fname not in ['__init__.py', '__pycache__']:
                missing_files.append(fname)
        for fname in mentioned_files:
            if fname in mentioned_files and fname not in actual_files:
                extra_described.append(fname)

        if extra_described:
            checks.append(("SKILL.md提到文件但代码不存在", False,
                            f"提及但不存在: {', '.join(extra_described)}"))
        else:
            checks.append(("SKILL.md文件描述一致性", True,
                            f"提及{len(mentioned_files)}个文件，代码均存在"))
    else:
        checks.append(("SKILL.md文件描述一致性", None, "_tools/目录不存在（跳过）"))

    # ── Phase 3.6: 自适应版本顺序检测 ──
    log("  📋 Phase 3.6: README 版本历史表格顺序检测（自适应）")
    # 从 README 表格提取所有版本号，判断升降序，然后验证 meta_ver 位置是否正确
    all_readme_vers = []
    for line in readme_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        # 跳过表头和分隔线
        if re.match(r'^\|\s*[-:]+[-:\s]*\|', stripped):
            continue
        # 排除含代码/非版本数字的行（如行号、分数等）
        if not re.search(r'v\d+\.\d+\.\d+', stripped):
            continue
        vm = re.search(r'v\d+\.\d+\.\d+', stripped)
        if vm:
            all_readme_vers.append(vm.group(0).lstrip('v'))

    if len(all_readme_vers) >= 2:
        # 判断升降序
        vers_nums = []
        for v in all_readme_vers:
            parts = v.split('.')
            if len(parts) == 3:
                try:
                    vers_nums.append(int(parts[0])*100 + int(parts[1])*10 + int(parts[2]))
                except ValueError:
                    continue  # 跳过无效版本格式

        if len(vers_nums) < 2:
            checks.append(("README版本顺序（自适应）", None,
                            f"有效版本数不足（{len(vers_nums)}个），跳过"))
        else:
            # 检测是否为降序（大部分仓库用降序）
            is_desc = all(vers_nums[i] >= vers_nums[i+1] for i in range(len(vers_nums)-1))
            is_asc = all(vers_nums[i] <= vers_nums[i+1] for i in range(len(vers_nums)-1))

            if is_desc:
                expected_pos = "首条"
                expected_ver = all_readme_vers[0]
                direction = "降序（最新在前）"
            elif is_asc:
                expected_pos = "末条"
                expected_ver = all_readme_vers[-1]
                direction = "升序（最旧在前）"
            else:
                direction = "无规律"
                expected_ver = meta_ver

            # 检查 meta_ver 是否在正确位置
            if is_desc:
                if readme_first_ver == expected_ver:
                    checks.append(("README版本顺序（自适应）", True,
                                    f"{direction}，首条={readme_first_ver} ✓"))
                else:
                    checks.append(("README版本顺序（自适应）", False,
                                    f"{direction}，首条={readme_first_ver}，应为末条={expected_ver}"))
            elif is_asc:
                if readme_first_ver == expected_ver:
                    checks.append(("README版本顺序（自适应）", True,
                                    f"{direction}，首条={readme_first_ver}=最旧（OK），末条应为最新={expected_ver} ✓"))
                else:
                    checks.append(("README版本顺序（自适应）", False,
                                    f"{direction}，首条={readme_first_ver}，末条应为最新={expected_ver}"))


    # ── 输出结果 ──
    log("")
    failed = [(n, d) for n, ok, d in checks if not ok]
    passed = [(n, d) for n, ok, d in checks if ok]

    for name, detail in passed:
        log(f"  ✅ {name}: {detail}")
    for name, detail in failed:
        log(f"  ❌ {name}: {detail}")

    log("")
    if failed:
        log(f"")
        log(f"  ❌ sync-checker 发现 {len(failed)} 项问题，内容完整性不通过。")
        log(f"  ❌ bump push 已成功，但内容完整性未通过，违反发布标准。")
        log(f"")
        log(f"  → 请修复上述问题后，重新运行 skill-bump。")
        fatal(f"步骤13: sync-checker 发现 {len(failed)} 项违规，内容完整性校验失败")
        return False  # never reached
    else:
        log(f"  ✅ sync-checker 全部通过（{len(passed)} 项）")
        return True


# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────
def _parse_args():
    """解析命令行参数"""
    import argparse
    parser = argparse.ArgumentParser(
        description="skill-bump.py — Denny Skill 仓库版本 bump 唯一执行入口",
        epilog="示例:\n  python3 skill-bump.py ./Denny-taotie v3.4.0 '修复XX问题'\n  python3 skill-bump.py ./Denny-taotie v3.4.0 '修复XX问题' --desc-file changes.md\n  python3 skill-bump.py ./Denny-48-laws-of-power v1.1.0 '新增XX skill' --book"
    )
    parser.add_argument("repo_path", help="仓库路径")
    parser.add_argument("version", help="版本号（x.y.z 或 vx.y.z）")
    parser.add_argument("change_message", nargs='?', default="版本更新", help="变更摘要（一行，用于表格行）")
    parser.add_argument("--desc-file", dest="desc_file", default=None,
                        help="详细描述文件路径（Markdown，用于 CHANGELOG section）")
    parser.add_argument("--book", dest="book", action="store_true", default=False,
                        help="书籍拆解类仓库（有多 skills/ 子目录）")
    args = parser.parse_args()
    return args


def main():
    args = _parse_args()

    repo_path = args.repo_path
    raw_version = args.version
    change_message = args.change_message
    desc_file = args.desc_file

    # 验证 version 格式
    if not re.match(r"v?\d+\.\d+\.\d+", raw_version):
        fatal(f"version 格式错误（应为 x.y.z 或 vx.y.z）: {raw_version}")

    # 标准化 version：确保有 v 前缀
    version = raw_version if raw_version.startswith('v') else f'v{raw_version}'

    # 🟢P1：中文检测升级为强制
    import unicodedata
    has_cjk = any('CJK' in unicodedata.name(c, '') for c in change_message if c.strip())
    if not has_cjk:
        fatal(f"❌ change_message 必须包含中文描述。当前: '{change_message}'\n   示例: '修复XX问题' 或 '新增XX功能'")

    # 🟢P2：读取详细描述文件（可选）
    desc_content = None
    if desc_file:
        df = Path(desc_file)
        if not df.exists():
            fatal(f"--desc-file 文件不存在: {desc_file}")
        desc_content = df.read_text(encoding="utf-8").strip()
        log(f"✅ 已读取详细描述文件: {desc_file} ({len(desc_content)} chars)")

    print(f"\n{'='*60}")
    print(f"skill-bump: {Path(repo_path).name} → {version}")
    print(f"{'='*60}\n", flush=True)

    repo_path = step1_validate_repo(Path(repo_path))
    is_book = args.book or (repo_path / "skills").is_dir()
    if is_book:
        log("📚 书籍拆解类模式（检测到 skills/ 目录）")
    step2_parse_frontmatter(repo_path)
    step3_create_version_doc(repo_path, version, change_message)
    step5_update_changelog(repo_path, version, change_message, desc_content=desc_content)
    step6_update_readme(repo_path, version, change_message)
    step7_update_meta(repo_path, version)
    step8_update_skill_frontmatter(repo_path, version, is_book=is_book)
    step4_snapshot_skill(repo_path, version)  # 在 step8 之后快照，捕获更新后的 SKILL.md
    step85_check_readme_stale(repo_path, version)
    step85b_check_versions_dir(repo_path, version)
    pushed = step9_git_operations(repo_path, version, change_message)
    if pushed:
        step12_verify(repo_path)

    # 步骤13: skill-sync-checker（push成功后，内容完整性最后防线）
    sync_ok = step13_sync_checker(repo_path)

    print(f"\n{'='*60}")
    if sync_ok:
        print(f"✅ bump 完成: {version}")
        print(f"{'='*60}")
    # if not sync_ok: fatal() above already exited, so we never reach here

if __name__ == "__main__":
    main()
