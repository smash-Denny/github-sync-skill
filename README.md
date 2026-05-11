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
| **v1.0.6** | 修复bump脚本未更新README版本历史的遗漏；新增step13跨文件一致性验证 |
| **v1.0.5** | step13违规升级为fatal必阻止；修复README版本历史顺序bug |
| **v1.0.4** | versions/升级为fail-fast；README修复版本历史重复问题 |
| **v1.0.3** | 新增versions/快照缺失advisory检查 |
| **v1.0.2** | 新增post-sync required-file guard（fail-fast） |
| **v1.0.1** | 修复book-class repo缺少README.md的遗漏 |
| **v1.0.0** | 初始版本，支持书籍拆解类与独立工具类自动识别 |
---

*由 Denny-cangjie v1.7 维护*
