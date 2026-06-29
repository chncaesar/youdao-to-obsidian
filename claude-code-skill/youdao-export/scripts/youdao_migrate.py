#!/usr/bin/env python3
"""
有道云笔记 → Obsidian Markdown 迁移脚本

扫描有道云 Mac 客户端本地数据目录，提取所有笔记（含正文），
转换为标准 Markdown 文件。

用法:
    python3 youdao_migrate.py
     python3 youdao_migrate.py --account user@example.com
    python3 youdao_migrate.py --output ~/Desktop/obsidian
    python3 youdao_migrate.py --base-dir "/path/to/ynote-desktop"

支持的笔记格式:
  - orgEditorType=0（新版编辑器）：本地 JSON 块结构 or 纯 Markdown 文件
  - orgEditorType=1（旧版编辑器）：contenttable 中的纯文本
"""

import sqlite3
import json
import os
import sys
import re
import time
import argparse
import configparser
from bs4 import BeautifulSoup
import warnings
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ------------------------------------------------------------
# 配置（可通过命令行参数覆盖）
# ------------------------------------------------------------
def _get_default_base_dir() -> Path:
    if os.name == "posix":
        candidates = [
            Path(os.path.expanduser("~/.config/ynote-desktop")),
            Path(os.path.expanduser(
                "~/Library/Containers/ynote-desktop/Data/Library/Application Support/ynote-desktop"
            )),
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return candidates[0]
    return Path(os.path.expanduser("~/.config/ynote-desktop"))

DEFAULT_BASE_DIR = _get_default_base_dir()


def parse_args():
    p = argparse.ArgumentParser(
        description="有道云笔记 → Obsidian Markdown 迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s
  %(prog)s --account user@example.com
  %(prog)s --output ~/Desktop/obsidian
  %(prog)s --base-dir "/path/to/ynote-desktop" --account my@email.com
        """
    )
    p.add_argument("--base-dir", default=None,
                   help=f"有道云笔记本地数据目录（默认自动检测: {DEFAULT_BASE_DIR}）")
    p.add_argument("--account", default=None,
                   help="账号邮箱（默认自动检测第一个找到的账号目录）")
    p.add_argument("--output", default=None,
                   help="输出目录（默认 ~/Desktop/obsidian）")
    p.add_argument("--oss", action="store_true", default=False,
                   help="启用图片/附件上传到阿里云 OSS")
    p.add_argument("--oss-prefix", default="youdao-notes",
                   help="OSS 存储路径前缀（默认: youdao-notes）")
    return p.parse_args()


def detect_account(base_dir: Path) -> str:
    """自动检测 base_dir 下的第一个账号目录"""
    for entry in sorted(base_dir.iterdir()):
        if entry.is_dir() and "@" in entry.name:
            ynote_data = entry / "ynote-data"
            if ynote_data.is_dir():
                return entry.name
    return None


def detect_base_dir() -> Path:
    """自动检测有道云笔记的数据目录（macOS / Linux）"""
    candidates = [
        Path(os.path.expanduser("~/.config/ynote-desktop")),
        Path(os.path.expanduser(
            "~/Library/Containers/ynote-desktop/Data/Library/Application Support/ynote-desktop"
        )),
        Path(os.path.expanduser(
            "~/Library/Application Support/ynote-desktop"
        )),
    ]
    for c in candidates:
        if c.is_dir():
            for entry in c.iterdir():
                if entry.is_dir() and "@" in entry.name and (entry / "ynote-data").is_dir():
                    return c
    return candidates[0]


# ------------------------------------------------------------
# OSS 配置
# ------------------------------------------------------------
MIME_EXT_MAP = {
    "image/png": ".png",
    "image/png;": ".png",
    "image/jpeg": ".jpg",
    "image/jpeg;": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/webp;": ".webp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/xml": ".xml",
    "application/x-sh": ".sh",
    "application/octet-stream": ".bin",
}


def load_oss_config() -> tuple | None:
    """加载 OSS 配置：环境变量优先，fallback ~/.ossutilconfig
    成功返回 (bucket_name, oss2.Bucket, endpoint)，失败返回 None"""
    bucket = os.environ.get("OSS_BUCKET", "")
    ak = os.environ.get("OSS_ACCESS_KEY_ID", "")
    sk = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    endpoint = os.environ.get("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")

    if not (bucket and ak and sk):
        config_path = os.path.expanduser("~/.ossutilconfig")
        if os.path.isfile(config_path):
            try:
                cp = configparser.ConfigParser()
                cp.read(config_path)
                ak = cp.get("Credentials", "accessKeyID", fallback="")
                sk = cp.get("Credentials", "accessKeySecret", fallback="")
                bucket = os.environ.get("OSS_BUCKET", cp.get("Credentials", "bucket", fallback=""))
                endpoint = cp.get("Credentials", "endpoint", fallback="oss-cn-hangzhou.aliyuncs.com")
            except Exception as e:
                print(f"⚠ 读取 ~/.ossutilconfig 失败: {e}")

    if not (bucket and ak and sk):
        return None

    import oss2
    auth = oss2.Auth(ak, sk)
    endpoint_url = f"https://{endpoint}" if not endpoint.startswith("http") else endpoint
    oss_bucket = oss2.Bucket(auth, endpoint_url, bucket)
    return bucket, oss_bucket, endpoint


def oss_upload(local_path: str, oss_path: str, oss_bucket) -> bool:
    """使用 oss2 SDK 上传单个文件到 OSS，返回是否成功"""
    if not os.path.isfile(local_path):
        return False

    for attempt in range(3):
        try:
            oss_bucket.put_object_from_file(oss_path.lstrip("/"), local_path)
            return True
        except oss2.exceptions.OssError as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  ⚠ 上传失败: {e}")
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  ⚠ 上传失败: {e}")
    return False


def get_ext_from_media_type(media_type: str) -> str:
    """从 MIME 类型获取文件扩展名"""
    if not media_type:
        return ""
    media_type = media_type.strip()
    return MIME_EXT_MAP.get(media_type, ".bin")


# ------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符（保留中文/英文/数字/常用符号）"""
    illegal = r'[<>:"/\\|?*]'
    name = re.sub(illegal, "_", name)
    name = name.strip().strip(".")
    if len(name) > 200:
        name = name[:200]
    if not name:
        name = "untitled"
    return name


def pretty_date(timestamp_s: int) -> str:
    """整数时间戳（秒）→ YYYY-MM-DD"""
    if not timestamp_s:
        return "unknown"
    try:
        return datetime.fromtimestamp(timestamp_s).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        return "unknown"


# ------------------------------------------------------------
# 新版编辑器 JSON Block 结构 → Markdown
# ------------------------------------------------------------
# Youdao 新版编辑器使用自定义 JSON block tree 存储富文本。
# 块类型（key "6"）：p=段落, h=标题, co=代码, t=表格, im=图片,
#   l=列表, q=引用, hr=分割线, tc=表格单元格
# 内联样式（key "9" 数组）：b=加粗, i=斜体, s=删除线, u=下划线,
#   c=文字颜色, fs=字号, li=链接, il=行内代码

# Module-level OSS state (set by main() when --oss enabled)
_oss_bucket = None       # oss2.Bucket instance
_oss_bucket_name = ""
_oss_endpoint = ""
_oss_prefix = ""
_url_cache = {}          # old_url → new_url
_resource_map = {}       # resource_id → {path, mediaType, title}
_oss_stats = {"uploaded": 0, "skipped": 0, "failed": 0, "cached": 0}

def convert_inline(segments: list) -> str:
    """将内联内容片段数组转为 Markdown 行内文本"""
    if not segments:
        return ""
    result = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = seg.get("8", "")
        formats = seg.get("9", [])
        if not formats:
            result.append(text)
            continue

        prefixes = []
        suffixes = []
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            kind = fmt.get("2", "")
            if kind == "b":
                prefixes.append("**")
                suffixes.append("**")
            elif kind == "i":
                prefixes.append("*")
                suffixes.append("*")
            elif kind == "s":
                prefixes.append("~~")
                suffixes.append("~~")
            elif kind == "u":
                prefixes.append("<u>")
                suffixes.append("</u>")
            elif kind == "li":
                url = ""
                if isinstance(fmt.get("4"), dict):
                    url = fmt["4"].get("hf", "")
                prefixes.append("[")
                suffixes.append(f"]({url})")
            elif kind == "il":
                prefixes.append("`")
                suffixes.append("`")
            elif kind in ("c", "fs"):
                pass

        result.append("".join(prefixes) + text + "".join(reversed(suffixes)))

    return "".join(result)


def _resolve_image_url(original_url: str, alt_text: str) -> str:
    """将图片 URL 转换为 OSS URL（上传后）；非 youdao 的直接返回原 URL"""
    if not _oss_bucket or not original_url:
        return original_url

    if original_url in _url_cache:
        _oss_stats["cached"] += 1
        return _url_cache[original_url]

    if "note.youdao.com" not in original_url:
        return original_url

    resource_id = original_url.rstrip("/").rsplit("/", 1)[-1]
    info = _resource_map.get(resource_id)

    if not info:
        _oss_stats["skipped"] += 1
        return original_url

    local_path = info["path"]
    if not os.path.isfile(local_path):
        _oss_stats["skipped"] += 1
        return original_url

    title = info.get("title", "")
    media_type = info.get("media_type", "")
    ext = get_ext_from_media_type(media_type)
    basename = resource_id
    if title and title.strip():
        safe_title = sanitize_filename(title.strip())
        if "." in safe_title:
            basename = os.path.splitext(safe_title)[0]
        else:
            basename = safe_title
    filename = f"{resource_id}_{basename}{ext}"

    oss_rel_path = f"{_oss_prefix}/{filename}"

    if oss_upload(local_path, oss_rel_path, _oss_bucket):
        new_url = f"https://{_oss_bucket_name}.{_oss_endpoint}/{oss_rel_path}"
        _url_cache[original_url] = new_url
        _oss_stats["uploaded"] += 1
        return new_url
    else:
        _oss_stats["failed"] += 1
        return original_url


def convert_blocks(blocks: list, indent_level: int = 0) -> str:
    """递归转换 JSON block tree → Markdown 文本"""
    md_lines = []

    for blk in blocks:
        if not isinstance(blk, dict):
            continue

        block_type = blk.get("6", "p")
        props = blk.get("4", {})
        children = blk.get("5", [])
        inline = blk.get("7", [])

        if block_type == "h":
            level_str = props.get("l", "h1")
            level = int(level_str[1]) if level_str.startswith("h") else 1
            level = max(1, min(6, level))
            text = convert_inline(inline)
            if text.strip():
                md_lines.append(f"{'#' * level} {text.strip()}")
            md_lines.append("")

        elif block_type == "co":
            lang = props.get("la", "")
            code_text = _extract_all_text(children)
            md_lines.append(f"```{lang}")
            md_lines.append(code_text.rstrip())
            md_lines.append("```")
            md_lines.append("")

        elif block_type == "im":
            url = props.get("u", "")
            alt = convert_inline(inline) or "image"
            resolved_url = _resolve_image_url(url, alt)
            md_lines.append(f"![{alt}]({resolved_url})")
            md_lines.append("")

        elif block_type == "t":
            md_lines.extend(_convert_table(children))
            md_lines.append("")

        elif block_type == "l":
            is_ordered = (props.get("lt", "unordered") == "ordered")
            for item in children:
                if isinstance(item, dict):
                    li_text = _extract_inline_from_block(item)
                    indent = "    " * indent_level
                    prefix = "1." if is_ordered else "-"
                    md_lines.append(f"{indent}{prefix} {li_text}")
            md_lines.append("")

        elif block_type == "q":
            quote_text = _extract_inline_from_block(blk)
            for line in quote_text.split("\n"):
                md_lines.append(f"> {line.strip()}" if line.strip() else ">")
            md_lines.append("")

        elif block_type == "hr":
            md_lines.append("---")
            md_lines.append("")

        elif block_type == "tc":
            pass  # 表格单元格由 _convert_table 处理

        else:  # p 或未知类型
            text = convert_inline(inline)
            child_text = convert_blocks(children, indent_level)
            if child_text.strip():
                if text.strip():
                    md_lines.append(text.strip())
                md_lines.append(child_text.rstrip())
            elif text.strip():
                md_lines.append(text.strip())
            md_lines.append("")

    return "\n".join(md_lines)


def _extract_all_text(blocks: list) -> str:
    """递归提取块中所有纯文本（用于代码块等）"""
    texts = []
    for blk in blocks:
        if not isinstance(blk, dict):
            continue
        for seg in (blk.get("7") or []):
            if isinstance(seg, dict) and "8" in seg:
                texts.append(seg["8"])
    return "\n".join(texts)


def _extract_inline_from_block(blk: dict) -> str:
    """从单个块中提取内联文本"""
    inline = blk.get("7", [])
    text = convert_inline(inline)
    for child in (blk.get("5") or []):
        if isinstance(child, dict):
            ct = convert_inline(child.get("7", []))
            if ct:
                text += " " + ct
    return text.strip()


def _convert_table(rows: list) -> list:
    """将 JSON 表格行转为 Markdown 表格"""
    md_rows = []
    is_first = True
    for row in rows:
        if not isinstance(row, dict):
            continue
        cell_texts = []
        for cell in (row.get("5") or []):
            if isinstance(cell, dict):
                ct = _extract_cell_text(cell).replace("|", "\\|").replace("\n", " ")
                cell_texts.append(ct)
            else:
                cell_texts.append("")
        if not cell_texts:
            continue
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if is_first:
            md_rows.append("| " + " | ".join(["---"] * len(cell_texts)) + " |")
            is_first = False
    return md_rows


def _extract_cell_text(cell: dict) -> str:
    """提取表格单元格文本（递归处理嵌套块结构）"""
    texts = []

    def _collect_text(block: dict):
        """递归收集 block 树中的所有文本"""
        if not isinstance(block, dict):
            return
        for seg in (block.get("7") or []):
            if isinstance(seg, dict) and "8" in seg:
                t = seg["8"]
                for fmt in (seg.get("9") or []):
                    if isinstance(fmt, dict) and fmt.get("2") == "b":
                        t = f"**{t}**"
                texts.append(t)
        for child in (block.get("5") or []):
            _collect_text(child)

    for child in (cell.get("5") or []):
        _collect_text(child)
    return "".join(texts)


def json_blocks_to_markdown(raw: str) -> str:
    """将有道云 JSON block 格式转为 Markdown"""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if not isinstance(obj, dict) or "5" not in obj or not isinstance(obj.get("5"), list):
        return raw

    return convert_blocks(obj["5"])


# ------------------------------------------------------------
# 旧版编辑器纯文本 → Markdown（简单清洗）
# ------------------------------------------------------------
def plain_text_to_markdown(text: str) -> str:
    """将旧版编辑器的纯文本清洗为 Markdown"""
    if not text or not text.strip():
        return ""

    md_indicators = ["##", "```", "| ", "![", "[", "**", "* "]
    if any(text.strip().startswith(ind) for ind in md_indicators):
        return text

    if text.count("<") > 3 and text.count(">") > 3:
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text("\n", strip=True)

    return text


# ------------------------------------------------------------
# 主迁移逻辑
# ------------------------------------------------------------
def build_folder_tree(main_cursor) -> dict:
    """构建文件夹层级树（来自 note_book 表），返回 {fileId: path_string}"""
    folders = main_cursor.execute(
        "SELECT fileId, title, parentId FROM note_book "
        "WHERE (del IS NULL OR del=0) AND (deleted IS NULL)"
    ).fetchall()

    folder_map = {}
    children_map = defaultdict(list)
    for fid, title, pid in folders:
        folder_map[fid] = sanitize_filename(title)
        children_map[pid].append(fid)

    folder_paths = {}

    def traverse(pid: str, parent_path: str):
        for fid in children_map.get(pid, []):
            name = folder_map.get(fid, "Unknown")
            path = os.path.join(parent_path, name) if parent_path else name
            folder_paths[fid] = path
            traverse(fid, path)

    traverse("1", "")

    for fid in folder_map:
        if fid not in folder_paths:
            folder_paths[fid] = folder_map[fid]

    return folder_paths


def main():
    args = parse_args()

    # 确定数据目录
    base_dir = Path(args.base_dir) if args.base_dir else detect_base_dir()

    # 确定账号
    account = args.account or detect_account(base_dir)
    if not account:
        print("❌ 未找到有道云笔记账号目录。请用 --account 指定账号邮箱。")
        print(f"   数据目录: {base_dir}")
        sys.exit(1)

    data_dir = base_dir / account / "ynote-data"
    main_db = data_dir / f"{account}.db"
    content_db = data_dir / f"{account}-content.db"

    # 确定输出目录
    output_dir = Path(os.path.expanduser(args.output)) if args.output else \
                 Path(os.path.expanduser("~/Desktop/obsidian"))

    print("=" * 60)
    print("有道云笔记 → Obsidian Markdown 迁移工具")
    print("=" * 60)
    print(f"📂 数据目录: {base_dir}")
    print(f"👤 账号:     {account}")
    print(f"📁 输出目录: {output_dir}")

    if not main_db.exists():
        print(f"❌ 主数据库不存在: {main_db}")
        sys.exit(1)
    if not content_db.exists():
        print(f"❌ 内容数据库不存在: {content_db}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    main_conn = sqlite3.connect(str(main_db))
    main_cur = main_conn.cursor()
    content_conn = sqlite3.connect(str(content_db))
    content_cur = content_conn.cursor()

    # ---- OSS 初始化 ----
    global _oss_bucket, _oss_bucket_name, _oss_endpoint, _oss_prefix, _resource_map
    if args.oss:
        cfg = load_oss_config()
        if cfg is None:
            print("❌ OSS 配置未找到。请设置以下环境变量：")
            print("   export OSS_BUCKET=your-bucket")
            print("   export OSS_ACCESS_KEY_ID=your-ak")
            print("   export OSS_ACCESS_KEY_SECRET=your-sk")
            print("   export OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com  # 可选")
            print("   或配置 ~/.ossutilconfig 并设置 OSS_BUCKET 环境变量")
            sys.exit(1)
        bucket_name, oss_bucket, endpoint = cfg
        _oss_bucket = oss_bucket
        _oss_bucket_name = bucket_name
        _oss_endpoint = endpoint
        _oss_prefix = args.oss_prefix.strip("/")

        print(f"☁️  OSS 已启用: oss://{bucket_name}/{_oss_prefix}/")
        print(f"   Endpoint: {endpoint}")

        # 读取 resource 表，构建 resourceID → {path, mediaType, title} 映射
        print("📦 读取资源缓存...")
        resources = main_cur.execute(
            "SELECT resourceID, entry, mediaType, title FROM resource WHERE entry IS NOT NULL AND entry != ''"
        ).fetchall()
        for rid, entry, mime, title in resources:
            _resource_map[rid] = {
                "path": entry,
                "media_type": (mime or "").strip(),
                "title": title or "",
            }
        print(f"   共 {len(_resource_map)} 个资源文件")
    else:
        rc = main_cur.execute(
            "SELECT COUNT(*) FROM resource WHERE entry IS NOT NULL AND entry != ''"
        ).fetchone()[0]
        if rc > 0:
            print()
            print("❌ 笔记中包含图片/附件（约 {} 个），但未启用 OSS 上传。".format(rc))
            print("   不使用 --oss 会导致 Markdown 中的图片链接指向有道云域名，离线不可用。")
            print()
            print("   请设置 OSS 环境变量后重新运行：")
            print("     export OSS_BUCKET=your-bucket")
            print("     export OSS_ACCESS_KEY_ID=your-ak")
            print("     export OSS_ACCESS_KEY_SECRET=your-sk")
            print("  然后执行:")
            print("     python3 ... --oss")
            sys.exit(1)

    print("📂 构建文件夹结构...")
    folder_paths = build_folder_tree(main_cur)
    print(f"   共 {len(folder_paths)} 个文件夹")

    notes = main_cur.execute("""
        SELECT
            fileId, title, parentId, dir, orgEditorType,
            noteType, entryPath, createTime, modifyTime,
            deleted, del, entryType
        FROM note
        WHERE dir = 0
          AND (deleted IS NULL)
          AND (del IS NULL OR del = 0)
        ORDER BY createTime
    """).fetchall()

    print(f"📝 共 {len(notes)} 条笔记待处理")

    all_content = {}
    for row in content_cur.execute(
        "SELECT fileId, content, title FROM contenttable WHERE content IS NOT NULL AND content != ''"
    ):
        all_content[row[0]] = (row[1], row[2])

    stats = {
        "success": 0,
        "skipped": 0,
        "no_content": 0,
        "json_converted": 0,
        "markdown_direct": 0,
        "plain_text": 0,
        "errors": 0,
    }

    for idx, note in enumerate(notes):
        (file_id, title, parent_id, _, org_editor, _,
         entry_path, create_time, modify_time, _, _, _) = note

        if not title or not title.strip():
            title = "未命名笔记"

        safe_title = sanitize_filename(title)
        if not safe_title:
            stats["skipped"] += 1
            continue

        # 确定输出子目录
        if parent_id and parent_id in folder_paths:
            sub_dir = output_dir / folder_paths[parent_id]
        else:
            sub_dir = output_dir / "未分类"
        sub_dir.mkdir(parents=True, exist_ok=True)

        base_path = sub_dir / f"{safe_title}.md"
        final_path = base_path
        counter = 1
        while final_path.exists():
            final_path = sub_dir / f"{safe_title}_{counter}.md"
            counter += 1

        # ---- 提取正文 ----
        markdown_body = ""

        # 方法 1：本地文件
        if entry_path and os.path.exists(entry_path):
            raw = ""
            try:
                with open(entry_path, "r", encoding="utf-8") as f:
                    raw = f.read()
            except UnicodeDecodeError:
                try:
                    with open(entry_path, "r", encoding="gbk") as f:
                        raw = f.read()
                except Exception:
                    raw = ""

            if raw:
                if raw[:6] == "SQLite":
                    print(f"  ⚠ {safe_title}: 本地文件是 SQLite 格式，跳过")
                    stats["skipped"] += 1
                    continue

                if raw.strip().startswith("{"):
                    markdown_body = json_blocks_to_markdown(raw)
                    if markdown_body != raw:
                        stats["json_converted"] += 1
                    else:
                        markdown_body = raw
                else:
                    markdown_body = raw
                    stats["markdown_direct"] += 1

        # 方法 2：contenttable
        if not markdown_body and file_id in all_content:
            content, content_title = all_content[file_id]
            if content:
                markdown_body = plain_text_to_markdown(content)
                if markdown_body:
                    stats["plain_text"] += 1
                if content_title and content_title.strip():
                    safe_title = sanitize_filename(content_title.strip())

        # 方法 3：search db fallback
        if not markdown_body:
            try:
                search_db = data_dir / f"{account}-search.db"
                if search_db.exists():
                    s_conn = sqlite3.connect(str(search_db))
                    s_row = s_conn.execute(
                        "SELECT file_content FROM file_content_table WHERE file_id=?",
                        (file_id,)
                    ).fetchone()
                    s_conn.close()
                    if s_row and s_row[0]:
                        markdown_body = s_row[0]
                        stats["plain_text"] += 1
            except Exception:
                pass

        if not markdown_body or not markdown_body.strip():
            stats["no_content"] += 1
            if (idx + 1) % 500 == 0:
                print(f"   进度: {idx+1}/{len(notes)}...")
            continue

        # ---- 写入文件 ----
        try:
            cdate = pretty_date(create_time) if create_time else "unknown"
            mdate = pretty_date(modify_time) if modify_time else "unknown"

            frontmatter = f"""---
title: "{title.strip()}"
create_date: {cdate}
modify_date: {mdate}
source: youdao
original_id: {file_id}
---

"""
            with open(final_path, "w", encoding="utf-8") as f:
                f.write(frontmatter)
                f.write(markdown_body)

            stats["success"] += 1
        except Exception as e:
            print(f"  ❌ 写入失败 {safe_title}: {e}")
            stats["errors"] += 1

        if (idx + 1) % 500 == 0:
            print(f"   进度: {idx+1}/{len(notes)}...")

    main_conn.close()
    content_conn.close()

    print()
    print("=" * 60)
    print("迁移完成！")
    print(f"  ✅ 成功导出: {stats['success']} 篇")
    print(f"  ⏭️  跳过:     {stats['skipped']} 篇")
    print(f"  📄 无正文:    {stats['no_content']} 篇")
    if stats['errors']:
        print(f"  ❌ 错误:     {stats['errors']} 篇")
    print()
    print(f"  其中:")
    print(f"    - JSON block 结构转换: {stats['json_converted']} 篇")
    print(f"    - 直接 Markdown 保存: {stats['markdown_direct']} 篇")
    print(f"    - 纯文本提取:         {stats['plain_text']} 篇")
    print()
    print(f"📁 输出路径: {output_dir}")
    if args.oss:
        print()
        print("☁️  OSS 上传统计：")
        print(f"    - 已上传:    {_oss_stats['uploaded']} 个")
        print(f"    - 使用缓存:  {_oss_stats['cached']} 次")
        print(f"    - 跳过:      {_oss_stats['skipped']} 个")
        if _oss_stats['failed']:
            print(f"    - 失败:      {_oss_stats['failed']} 个")
    print("=" * 60)


if __name__ == "__main__":
    main()
