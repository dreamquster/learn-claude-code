import os
import sys
from anthropic import Anthropic
from pathlib import Path
from TodoManager import TodoManager
from SkillRegistry import SkillRegistry
from Compactor import persist_large_output, maybe_compact

SAFE_DIRS = [
    Path("/tmp/safe_dir"),
    Path(__file__).resolve().parent,
];

todo_manager = TodoManager()
skill_registry = SkillRegistry()
skill_registry.load_from_dir("skills")



def safe_path(p: str) -> Path:
    target = (Path.cwd() / p).resolve()
    if not any(d in target.parents or target == d for d in SAFE_DIRS):
        raise ValueError(f"Unsafe path detected: {target} not in {SAFE_DIRS}")
    return target

def run_read(p: str, limit: int = 50000) -> str:
    text = safe_path(p).read_text()
    lines = text.splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit]
    return "\n".join(lines)


TOOL_HANDLERS = {
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit", 50000)),
    "todo": lambda **kw: todo_manager.update(kw["items"]),
    "get_skill": lambda **kw: (
        lambda doc: f"# {doc.manifest.name}\n\n{doc.manifest.description}\n\n---\n\n{doc.body}"
        if doc is not None
        else f"Skill '{kw['name']}' not found. Available skills: {', '.join(m.name for m in skill_registry.list_skills()) or '(none)'}"
    )(skill_registry.get_skill(kw["name"])),
}

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the specified path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read",
                    "default": 50000,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "todo",
        "description": "Update the todo list with new items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "activeFrom": {"type": "string"},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "get_skill",
        "description": "Retrieve the full content of a registered skill by name. Skills are loaded from the skills/ directory at startup. Use this to get detailed instructions for a specific workflow or checklist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the skill to retrieve (e.g., 'code-review', 'git-workflow')",
                },
            },
            "required": ["name"],
        },
    },
]

def _block_to_dict(block) -> dict:
    """将 Anthropic SDK 的 block 对象（TextBlock / ToolUseBlock / ToolResultBlock）转为普通 dict。"""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if isinstance(block, dict):
        return block
    return dict(block)


def normalize_messages(messages: list) -> list:
    """将内部消息列表规范化为 API 可接受的格式。"""
    normalized = []

    for msg in messages:
        # Step 1: 剥离内部字段
        clean = {"role": msg["role"]}
        if isinstance(msg.get("content"), str):
            clean["content"] = msg["content"]
        elif isinstance(msg.get("content"), list):
            clean["content"] = [
                _block_to_dict(block)
                for block in msg["content"]
            ]
        normalized.append(clean)

    # Step 2: tool_result 配对补齐
    # 收集所有已有的 tool_result ID
    existing_results = set()
    for msg in normalized:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    existing_results.add(block.get("tool_use_id"))

    # 找出缺失配对的 tool_use, 插入占位 result
    for msg in normalized:
        if msg["role"] == "assistant" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if (block.get("type") == "tool_use"
                        and block.get("id") not in existing_results):
                    # 在下一条 user 消息中补齐
                    normalized.append({"role": "user", "content": [{
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": "(cancelled)",
                    }]})

    # Step 3: 合并连续同角色消息
    merged = [normalized[0]] if normalized else []
    for msg in normalized[1:]:
        if msg["role"] == merged[-1]["role"]:
            # 合并内容
            prev = merged[-1]
            prev_content = prev["content"] if isinstance(prev["content"], list) \
                else [{"type": "text", "text": prev["content"]}]
            curr_content = msg["content"] if isinstance(msg["content"], list) \
                else [{"type": "text", "text": msg["content"]}]
            prev["content"] = prev_content + curr_content
        else:
            merged.append(msg)

    return merged


client = Anthropic(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/anthropic",
)


def run_tool_loop(state) -> None:
    """
    与 LLM 对话，自动处理 tool_use → tool_result 循环，
    直到 LLM 不再调用 tool 为止。

    大输出自动持久化到磁盘（> PERSIST_THRESHOLD），
    messages 总大小超过 COMPACT_THRESHOLD 时触发压缩。
    """
    while True:
        # 检查是否需要压缩（每轮只做一次）
        maybe_compact(state)


        messages = normalize_messages(state["messages"])
        response = client.messages.create(
            model="deepseek-chat",
            max_tokens=4096,
            messages=messages,
            tools=TOOLS,
        )

        state["messages"].append({
            "role": "assistant",
            "content": response.content,
        })

        # Print text content if present
        for block in response.content:
            if block.type == "text":
                print("Assistant:", block.text)

        if response.stop_reason != "tool_use":
            return

        results = []
        todo_was_called = False
        for block in response.content:
            if block.type == "tool_use":
                tool_handler = TOOL_HANDLERS.get(block.name)
                if tool_handler:
                    output = tool_handler(**block.input)
                    # 大输出持久化
                    persisted = persist_large_output(block.id, output)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": persisted,
                    })
                    if block.name == "todo":
                        todo_was_called = True
                    # 追踪最近碰过的文件
                    if block.name == "read_file":
                        fpath = block.input.get("path", "")
                        if fpath and fpath not in state["recent_files"]:
                            state["recent_files"].append(fpath)

        if not todo_was_called:
            todo_manager.tick()

        if todo_manager.needs_reminder():
            results.insert(0, {
                "type": "text",
                "text": "<reminder>Refresh your plan before continuing.</reminder>",
            })

        state["messages"].append({
            "role": "user",
            "content": results,
        })
        state["turn_count"] += 1
        state["transition_reason"] = "tool_use"



def agent_loop(state):
    while True:
        # 等待用户输入
        try:
            query = input(">>> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query.strip():
            continue

        state["messages"].append({"role": "user", "content": query})
        run_tool_loop(state)


if __name__ == "__main__":
    state = {
        "messages": [],
        "results": [],
        "turn_count": 0,
        "transition_reason": None,
        "has_compacted": False,       # 这一轮之前是否已经做过完整压缩
        "last_summary": "",           # 最近一次压缩得到的摘要
        "recent_files": [],           # 最近碰过哪些文件，压缩后方便继续追踪
    }


    # 支持命令行参数作为首次输入
    if len(sys.argv) > 1:
        state["messages"].append({"role": "user", "content": " ".join(sys.argv[1:])})

    try:
        agent_loop(state)
    except KeyboardInterrupt:
        print("\nBye!")
