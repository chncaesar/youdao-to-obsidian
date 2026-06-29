# Youdao to Obsidian

将 [有道云笔记](https://note.youdao.com/) 客户端本地数据导出为 Markdown 文件，可直接导入 [Obsidian](https://obsidian.md/) 使用。

## 功能

- ✅ 完整导出所有笔记
- ✅ 保留原有文件夹层级结构
- ✅ 生成 YAML frontmatter（标题、创建日期、修改日期、原始 ID）
- ✅ 新版编辑器 JSON block → Markdown（含表格、代码块、图片、列表、引用）
- ✅ 旧版编辑器纯文本直接导出
- ✅ 图片/附件上传到阿里云 OSS，替换为公网 URL
- ✅ 支持命令行参数：账号、输出目录、数据目录

## 依赖

- Python 3.9+
- macOS / Linux（有道云笔记客户端）

```bash
pip3 install -r requirements.txt
```

## 快速使用

```bash
git clone https://github.com/chncaesar/youdao-to-obsidian.git
cd youdao-to-obsidian
pip3 install -r requirements.txt

# 设置 OSS 环境变量（必选）
export OSS_BUCKET=your-bucket
export OSS_ACCESS_KEY_ID=your-ak
export OSS_ACCESS_KEY_SECRET=your-sk
export OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com  # 可选

python3 claude-code-skill/youdao-export/scripts/youdao_migrate.py --oss --output ~/Desktop/obsidian
```

默认输出到 `~/Desktop/obsidian/`，直接用 Obsidian 打开该目录即可。`--oss` 为必选参数，笔记中的图片/附件会通过此配置上传到阿里云 OSS。

### 自定义参数

```bash
python3 claude-code-skill/youdao-export/scripts/youdao_migrate.py --oss --account your@email.com --output ~/Documents/MyVault
```

### OSS 上传说明

`--oss` 为必选参数。图片/附件会自动上传到 `oss://{bucket}/{oss-prefix}/`（默认前缀 `youdao-notes`），Markdown 中的 URL 替换为 OSS 公网地址。非有道云域名的外链图片保持原样。

> **注意**：有道云本地缓存并非全部图片的完整副本。客户端仅下载近期访问过的图片/附件，大量历史图片的本地文件可能缺失。`resource` 表中的记录数量不等于实际可上传数量。

## Claude Code 用户

将 `claude-code-skill/youdao-export/` 复制到技能目录：
- Claude Code：`~/.claude/skills/`
- OpenCode：`~/.config/opencode/skills/`

之后对话中说「导出有道云笔记」即可自动触发。

## 数据目录说明

有道云笔记客户端数据默认位于：

- **Linux**：`~/.config/ynote-desktop/`
- **macOS**：`~/Library/Containers/ynote-desktop/Data/Library/Application Support/ynote-desktop/`

目录结构：

```
ynote-desktop/
├── <账号邮箱>/              # 如 user@example.com
│   └── ynote-data/
│       ├── <账号>.db            # 主库（笔记元数据 + 文件夹树）
│       ├── <账号>-content.db    # 内容库（笔记正文）
│       └── <账号>-search.db     # 搜索索引（备用内容源）
└── databases/
```

## 工作原理

1. 从 `note_book` 表取文件夹层级
2. 从 `note` 表取所有非删除笔记
3. 正文来源（按优先级）：
   - 本地文件（新版编辑器 JSON block → Markdown）
   - contenttable 数据库（旧版编辑器）
   - search.db（最后备用）
4. 输出为 .md 文件

## License

MIT
