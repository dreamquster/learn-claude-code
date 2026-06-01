# {
#    "content": "Read the failing test",
#    "status": "pending" | "in_progress" | "completed",
#    "activeFrom": "Reading the failing test",
# }
# {
#    "items": [...],
#    "rounds_since_update": 0,
# }
#
class TodoManager:
    def __init__(self):
        self.todos = []
        self.rounds_since_update = 0
        self.has_ever_been_used = False

    def update(self, items: list) -> str:
        validated = []
        in_progress_count = 0
        for item in items:
            if item["status"] == "in_progress":
                in_progress_count += 1
            validated.append({
                "content": item["content"],
                "status": item["status"],
                "activeFrom": item.get("activeFrom"),
            })
        self.todos = validated
        self.rounds_since_update = 0
        self.has_ever_been_used = True
        return f"Updated todos. In progress: {in_progress_count}"

    def tick(self):
        self.rounds_since_update += 1

    def needs_reminder(self) -> bool:
        if not self.has_ever_been_used:
            return False
        if self.rounds_since_update < 3:
            return False
        # 所有 item 都 completed 了就不再提醒
        if self.todos and all(item["status"] == "completed" for item in self.todos):
            return False
        return True
    
    def render(self) -> str:
        if not self.todos:
            return "No todos yet."
        output = []
        for idx, item in enumerate(self.todos, 1):
            marker = {
                "pending":"[ ]",
                "in_progress":"[>]",
                "completed":"[x]"
            }[item["status"]]
            output.append(f"{marker} {item['content']}")
        return "\n".join(output)