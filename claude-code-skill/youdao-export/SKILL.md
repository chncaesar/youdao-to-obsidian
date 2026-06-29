---
name: youdao-export
description: 将有道云笔记 Mac 客户端本地数据导出为 Markdown 文件，适合导入 Obsidian。当用户提到「导出有道云笔记」「迁移有道云」「备份有道云」「有道云转 Markdown」「有道云转 Obsidian」「youdao export」时触发。
compatibility: Python 3.9+, beautifulsoup4, oss2, macOS / Linux
---

# 有道云笔记 → Obsidian Markdown 导出

将有道云笔记 Mac 客户端的本地 SQLite 数据导出为标准 Markdown 文件，保留文件夹层级、创建/修改日期等元数据。

## 数据目录定位

脚本会自动检测数据目录。各平台默认路径：

- **Linux**：`~/.config/ynote-desktop/`
- **macOS**：`~/Library/Containers/ynote-desktop/Data/Library/Application Support/ynote-desktop/`

目录结构（两个平台一致）：
```
ynote-desktop/
├── <账号邮箱>/          # 如 user@example.com
│   └── ynote-data/
│       ├── <账号>.db           # 主库（笔记元数据 + 文件夹树）
│       ├── <账号>-content.db   # 内容库（笔记正文）
│       ├── <账号>-search.db    # 搜索索引（备用内容源）
│       └── file/               # 新版编辑器本地文件
└── databases/
    └── Databases.db
```

如果数据不在默认路径，使用 `--base-dir` 手动指定。Linux 上从其他机器迁移数据时同样通过 `--base-dir` 指向拷贝后的目录。

## 执行导出

运行 skill 目录下的脚本：

```bash
python3 scripts/youdao_migrate.py
```

### 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--account` | 账号邮箱 | 自动检测（第一个含 @ 的目录） |
| `--output` | 输出目录 | `~/Desktop/obsidian` |
| `--base-dir` | 有道云数据根目录 | 自动检测（Linux: `~/.config/ynote-desktop`，macOS: `~/Library/Containers/...`） |
| `--oss` | 启用图片/附件上传到阿里云 OSS | 否 |
| `--oss-prefix` | OSS 存储路径前缀 | `youdao-notes` |

### 示例

```bash
# 设置 OSS 环境变量（必选）
export OSS_BUCKET=your-bucket
export OSS_ACCESS_KEY_ID=your-ak
export OSS_ACCESS_KEY_SECRET=your-sk
export OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com  # 可选

# 默认导出（自动检测账号，输出到 ~/Desktop/obsidian）
python3 scripts/youdao_migrate.py --oss

# 指定账号和输出目录
python3 scripts/youdao_migrate.py --oss --account user@example.com --output ~/Documents/ObsidianVault

# 指定非默认数据目录
python3 scripts/youdao_migrate.py --oss --base-dir "/Volumes/Backup/ynote-desktop" --account user@example.com

# Linux：从其他机器拷贝数据到当前机器后导出
python3 scripts/youdao_migrate.py --oss --base-dir /work/youdao-backups --account user@example.com --output /work/obsidian
```

## 导出内容

每个笔记输出为一个 `.md` 文件，包含 YAML frontmatter：

```yaml
---
title: "笔记标题"
create_date: 2020-09-30
modify_date: 2020-09-30
source: youdao
original_id: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA01
---
```

笔记按原有道云文件夹层级组织到对应子目录中。

## 工作原理

1. 从 `note_book` 表重建文件夹层级树
2. 从 `note` 表查询所有未删除笔记（~2325 条）
3. 通过三层 fallback 提取正文：
   - **本地文件**（新版编辑器 `orgEditorType=0`）：JSON block 结构 → Markdown
   - **contenttable**（旧版编辑器 `orgEditorType=1`）：纯文本
   - **search.db**（最后备用）
4. 新版编辑器 JSON block 支持：标题、段落、表格、代码块、图片、列表、引用、分割线、加粗/斜体/链接/行内代码

## OSS 图片上传

启用 `--oss` 后，脚本会将笔记中的图片/附件上传到阿里云 OSS，并将 Markdown 中的 URL 替换为 OSS 公网地址。

**凭证配置**（优先级从高到低）：
1. 环境变量：`OSS_BUCKET`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_ENDPOINT`（可选，默认 `oss-cn-hangzhou.aliyuncs.com`）
2. `~/.ossutilconfig` 文件（通过 `ossutil config` 生成）+ `OSS_BUCKET` 环境变量

**工作原理**：
- 从 `resource` 表读取有道云本地缓存的图片文件（~1971 个资源）
- 识别 JSON block 中的图片 URL，提取 resourceID
- 使用 oss2 Python SDK 上传到 OSS
- 外链图片（非 `note.youdao.com` 域名）保持原样

## 依赖

```bash
pip3 install beautifulsoup4 oss2
```
