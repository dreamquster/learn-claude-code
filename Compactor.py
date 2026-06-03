"""
会话压缩与工具输出持久化。

大输出（> PERSIST_THRESHOLD）自动存盘，messages 中只留预览；
messages 总大小超过 COMPACT_THRESHOLD 时触发完整压缩，
将历史替换为一条摘要消息，保留上下文连续性。
"""

from pathlib import Path

# 工具输出超过此阈值（字符数）则持久化到磁盘，不塞进 messages
PERSIST_THRESHOLD = 8000
# 所有 messages 总字符数超过此阈值则触发会话压缩
COMPACT_THRESHOLD = 50000


def _output_dir() -> Path:
    """持久化输出存放目录。"""
    d = Path.home() / ".learn-claude-code" / "persisted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_to_disk(tool_use_id: str, output: str) -> Path:
    """将大输出写入磁盘，返回文件路径。"""
    path = _output_dir() / f"{tool_use_id}.txt"
    path.write_text(output, encoding="utf-8")
    return path


def persist_large_output(tool_use_id: str, output: str) -> str:
    """工具输出超过阈值时，持久化到磁盘，只留预览。"""
    if len(output) <= PERSIST_THRESHOLD:
        return output

    stored_path = save_to_disk(tool_use_id, output)
    preview = output[:2000]
    return (
        "<persisted-output>\n"
        f"Full output saved to: {stored_path}\n"
        f"Preview:\n{preview}\n"
        "</persisted-output>"
    )


def messages_total_size(messages: list) -> int:
    """计算 messages 中所有文本的总字符数。"""
    total = 0
    for msg in messages:
        if isinstance(msg.get("content"), str):
            total += len(msg["content"])
        elif isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and "content" in block:
                    total += len(str(block["content"]))
    return total


def build_compaction_summary(state: dict) -> str:
    """根据 state 中的信息构建压缩摘要文本。"""
    parts = []
    if state.get("last_summary"):
        parts.append(f"Previous summary: {state['last_summary']}")
    if state.get("recent_files"):
        parts.append(f"Recently touched files: {', '.join(state['recent_files'])}")
    parts.append(f"Total turns so far: {state.get('turn_count', 0)}")
    return "\n".join(parts)


def compact_history(state: dict) -> list:
    """
    完整压缩：将整个 messages 替换为一条摘要消息。
    更新 state 中的压缩相关字段。
    """
    summary = build_compaction_summary(state)
    state["has_compacted"] = True
    state["last_summary"] = summary
    state["recent_files"] = list(dict.fromkeys(state.get("recent_files", [])))
    return [{
        "role": "user",
        "content": (
            "<compacted-history>\n"
            "The following is a summary of the conversation so far.\n\n"
            f"{summary}\n"
            "</compacted-history>"
        ),
    }]


def micro_compact(messages: list) -> None:
    """微压缩：只保留最近 3 条 tool_result 的完整内容，其余截断。"""
    tool_results = []
    for msg in messages:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results.append(block)
    for result in tool_results[:-3]:
        result["content"] = "[Earlier tool result omitted for brevity]"


def maybe_compact(state: dict) -> bool:
    """
    先做微压缩（截断较早的 tool_result），
    若仍超过阈值则执行完整压缩。
    返回是否执行了完整压缩。
    """
    micro_compact(state["messages"])
    total_size = messages_total_size(state["messages"])
    if total_size <= COMPACT_THRESHOLD:
        return False
    if state.get("has_compacted"):
        return False
    state["messages"] = compact_history(state)
    print(f"[System] Conversation compacted ({total_size} chars -> {len(state['messages'][0]['content'])} chars)")
    return True

