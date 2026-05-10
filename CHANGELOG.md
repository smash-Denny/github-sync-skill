# Changelog

## v1.0.2

- feat: post-sync required-file guard（上传后完整性检查，缺失 README.md / SKILL.md / _meta.json / references/INDEX.md 任一文件时 fail-fast 退出，exit 1）
- fix: book-class 同步时自动从 INDEX.md 生成 README.md（之前只有 tool-class 生成 README）
- fix: 修复 book-class repo 缺少 README.md 的历史遗漏

## v1.0.1

- fix: auto-generate README.md for book-class repos from INDEX.md

## v1.0.0

- 初始版本：强制分类 GitHub 同步脚本，支持书籍拆解类与独立工具类自动识别
