"""DEV-019: 探针验证 RedisSaver API — from_conn_string / async 读写 / adelete_thread

真实 API 与计划假设的差异(实测 langgraph-checkpoint-redis 0.5.2 / langgraph 1.2.11):
- 构造方法名是 from_conn_string (from_conn_info 不存在), 且是 @contextmanager
  classmethod: 必须用 `with` 块, 退出时自动关闭 redis 客户端
- 无 serializer 参数(默认 serde 即 JsonPlusSerializer 子类)
- 同步 RedisSaver 的 async 方法 (aput/aget_tuple) 是 BaseCheckpointSaver 的
  NotImplementedError 桩 — 异步图 (AsyncPregel) 必须用 AsyncRedisSaver
- 无 aclose / aget_state; 建索引用 asetup() (async) 或 setup() (sync)
- adelete_thread(thread_id) 直接收 thread_id 字符串
- redis 需带 RediSearch 模块(官方 redis:7-alpine 无 FT.* 命令,
  用 redis/redis-stack-server 镜像)
"""
import asyncio
import inspect
import sys

sys.stdout.reconfigure(encoding="utf-8")

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


async def main():
    print("from_conn_string 签名:", inspect.signature(AsyncRedisSaver.from_conn_string))
    async with AsyncRedisSaver.from_conn_string("redis://localhost:6379/0") as saver:
        print("serde 类型:", type(saver.serde).__name__,
              "(JsonPlusSerializer 子类 =", isinstance(saver.serde, JsonPlusSerializer), ")")
        print("async 方法:", [m for m in ("aget_tuple", "aput", "adelete_thread",
                                          "asetup", "aget_state", "aclose")
                              if hasattr(saver, m)])
        await saver.asetup()
        # 读写往返: 直接调 checkpoint 保存/读取接口
        cfg = {"configurable": {"thread_id": "probe-t1", "checkpoint_ns": ""}}
        checkpoint = {
            "v": 1, "ts": "2026-08-22T00:00:00Z", "id": "probe-c1",
            "channel_values": {"question": "测试", "allow_web_search": False},
            "channel_versions": {}, "versions_seen": {}, "pending_sends": [],
            "parent_checkpoint_id": None,
        }
        metadata = {"source": "probe", "step": 1, "writes": {}, "score": 1}
        await saver.aput(cfg, checkpoint, metadata, {})
        tup = await saver.aget_tuple(cfg)
        print("读回:", tup.checkpoint["channel_values"] if tup else None)
        await saver.adelete_thread(cfg["configurable"]["thread_id"])
        after = await saver.aget_tuple(cfg)
        print("删除后:", after)


if __name__ == "__main__":
    asyncio.run(main())
