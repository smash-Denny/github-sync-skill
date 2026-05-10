# Changelog

## v1.0.5（2026-05-11）

fix: step13违规检测升级为fatal(必阻止)；README版本历史补全v1.0.4

### 核心变化

<!-- 请补充具体变化点 -->

### 影响范围

<!-- 请补充影响范围 -->

---

## v1.0.3

- feat: 新增 versions/ 快照缺失 advisory 检查（post-sync 时提示，提示而非阻断）
- 注意：v1.0.1 和 v1.0.2 的 versions/ 快照已补全

## v1.0.2

- feat: post-sync required-file guard（上传后完整性检查，缺失 README.md / SKILL.md / _meta.json / references/INDEX.md 任一文件时 fail-fast 退出，exit 1）
- fix: book-class 同步时自动从 INDEX.md 生成 README.md（之前只有 tool-class 生成 README）
- fix: 修复 book-class repo 缺少 README.md 的历史遗漏

## v1.0.1

- fix: auto-generate README.md for book-class repos from INDEX.md

## v1.0.0

- 初始版本：强制分类 GitHub 同步脚本，支持书籍拆解类与独立工具类自动识别