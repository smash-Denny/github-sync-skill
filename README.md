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
