"""Basic task engine for multi-step goals (in-memory)."""

import uuid


class Task:
    def __init__(self, goal):
        self.task_id = uuid.uuid4().hex
        self.goal = goal
        self.plan = []
        self.current_step = 0
        self.completed_steps = []
        self.last_result = None
        self.status = "planning"


# Flag pembatalan global (sederhana).
_CANCEL_REQUESTED = False


def request_cancel():
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = True


def is_cancelled():
    return _CANCEL_REQUESTED


def reset_cancel():
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = False


class TaskEngine:
    def __init__(self):
        self.tasks = {}

    def create(self, goal):
        t = Task(goal)
        self.tasks[t.task_id] = t
        return t

    def set_plan(self, task_id, steps):
        t = self.tasks.get(task_id)
        if t:
            t.plan = list(steps or [])
            t.status = "running"
        return t

    def complete_step(self, task_id, result=None):
        t = self.tasks.get(task_id)
        if t:
            t.completed_steps.append(t.current_step)
            t.current_step = min(t.current_step + 1, len(t.plan))
            t.last_result = result
            if t.current_step >= len(t.plan) and t.plan:
                t.status = "completed"
        return t

    def fail(self, task_id, result=None):
        t = self.tasks.get(task_id)
        if t:
            t.last_result = result
            t.status = "failed"
        return t
