# Youdao to Obsidian

将 [有道云笔记](https://note.youdao.com/) Mac 客户端本地数据导出为 Markdown 文件，可直接导入 [Obsidian](https://obsidian.md/) 使用。

## 功能

- ✅ 完整导出所有笔记（2290+ 篇）
- ✅ 保留原有文件夹层级结构
- ✅ 生成 YAML frontmatter（标题、创建日期、修改日期、原始 ID）
- ✅ 新版编辑器 JSON block → Markdown（含表格、代码块、图片、列表、引用）
- ✅ 旧版编辑器纯文本直接导出
- ✅ 支持命令行参数：账号、输出目录、数据目录
- ✅ 自动检测 macOS 上有道云数据目录

## 依赖

- Python 3.9+
- macOS（有道云笔记 Mac 客户端）

```bash
pip3 install beautifulsoup4
```

## 快速使用

```bash
git clone https://github.com/chncaesar/youdao-to-obsidian.git
cd youdao-to-obsidian
pip3 install beautifulsoup4
python3 youdao_migrate.py
```

默认输出到 `~/Desktop/obsidian/`，直接用 Obsidian 打开该目录即可。

### 自定义参数

```bash
python3 youdao_migrate.py --account your@email.com --output ~/Documents/MyVault
```

## Claude Code 用户

将 `claude-code-skill/youdao-export/` 目录复制到 `~/.claude/skills/`，之后对 Claude Code 说「导出有道云笔记」即可自动触发。

## 数据目录说明

有道云笔记 Mac 客户端的数据默认位于：

```
~/Library/Containers/ynote-desktop/Data/Library/Application Support/ynote-desktop/
```

目录结构：

```
ynote-desktop/
├── <账号邮箱>/              # 如 caesar@163.com
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
