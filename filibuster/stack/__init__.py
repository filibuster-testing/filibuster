from collections import deque


class Stack:
    def __init__(self):
        self.stack = deque()

    def push(self, item):
        self.stack.append(item)
        return True

    def pop(self):
        return self.stack.pop()

    def size(self):
        return len(self.stack)

    def contains(self, item):
        return item in self.stack
