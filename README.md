# github-sync-skill.py

> Denny Skill 仓库强制分类同步脚本

## 功能

- 自动识别 skill 类型（书籍拆解类 vs 独立工具类）
- 根据类型选择正确的 GitHub repo 结构
- 一书一 repo / 一 skill 一 repo 自动分流
- 可选归档旧 repo

## 使用方法

```bash
# 书籍拆解类（自动识别）
python3 github-sync-skill.py ~/books/48-laws-of-power

# 独立工具类
python3 github-sync-skill.py ~/skills/Denny-taotie --repo-name Denny-taotie

# 归档旧repo
python3 github-sync-skill.py --archive-patterns Denny-48laws,Denny-WTFA --archive-note "Merged"
```

## 强制执行

**禁止直接调用 GitHub API 创建 Denny-* 仓库。**
必须使用本脚本。

## GitHub

https://github.com/smash-Denny/github-sync-skill

---

## Book-class Support

**Important (v1.0.1+)**: Book-class repos (those with `BOOK_OVERVIEW.md`) now automatically get a `README.md` generated from `INDEX.md` during sync. No manual README creation needed.

---

## 版本历史

| 版本 | 核心变化 |
|------|----------|
| **v1.0.2** | 新增 post-sync required-file guard（fail-fast）；book-class 自动生成 README.md |

| **v1.0.3** | 新增 versions/ 快照缺失 advisory 检查 || **v1.0.1** | 修复 book-class repo 缺少 README.md 的遗漏 |
| **v1.0.0** | 初始版本，支持书籍拆解类与独立工具类自动识别 |
| **[v1.0.5](#105)** | fix: step13违规检测升级为fatal(必阻止)；README版本历史补全v1.0.4 |

---

*由 Denny-cangjie v1.7 维护*