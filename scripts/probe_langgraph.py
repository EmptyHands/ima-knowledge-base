"""DEV-012: 验证 langgraph API 面(StateGraph/interrupt/Command/get_stream_writer/MemorySaver.delete_thread)"""
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer
from langgraph.checkpoint.memory import MemorySaver

m = MemorySaver()
print("imports OK")
print("delete_thread:", hasattr(m, "delete_thread"), "adelete_thread:", hasattr(m, "adelete_thread"))
assert hasattr(m, "adelete_thread"), "langgraph 版本过低, 需要 delete_thread 清中断线程"
