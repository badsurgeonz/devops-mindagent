import asyncio
import json
import logging

from app.config import cfg
from app.db.base import build_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit.consumer")

RETRY_MAX = 3
DEAD_LETTER_SUFFIX = ".dlq"


def _map_trace(envelope: dict) -> dict:
    p = envelope["payload"]
    return {
        "id": p["id"],
        "event_id": envelope["event_id"],
        "request_id": p["request_id"],
        "session_id": p.get("session_id"),
        "tenant_id": p["tenant_id"],
        "user_id": int(p["user_id"]),
        "query_text": p["query_text"],
        "provider": p.get("provider"),
        "model": p.get("model"),
        "status": p["status"],
        "cached": p.get("cached", False),
        "latency_ms": p.get("latency_ms"),
        "error_code": p.get("error_code"),
    }


def _map_tool_call(envelope: dict) -> dict:
    p = envelope["payload"]
    return {
        "event_id": envelope["event_id"],
        "trace_id": p["trace_id"],
        "tenant_id": p["tenant_id"],
        "tool_name": p["tool_name"],
        "arguments_json": p.get("arguments"),
        "result_json": p.get("result"),
        "status": p["status"],
        "latency_ms": p.get("latency_ms"),
    }


async def consume_loop(repo):
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        cfg.kafka.trace_topic,
        cfg.kafka.tool_topic,
        cfg.kafka.security_topic,
        bootstrap_servers=cfg.kafka.bootstrap_servers,
        group_id=cfg.kafka.group_id,
        enable_auto_commit=False,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    await consumer.start()
    try:
        async for msg in consumer:
            try:
                envelope = msg.value
                if envelope["event_type"] == "agent.trace.completed":
                    await repo.save_trace(_map_trace(envelope))
                elif envelope["event_type"] == "agent.tool.call":
                    await repo.save_tool_call(_map_tool_call(envelope))
                else:
                    logger.info("security event: %s", envelope["event_type"])
                await consumer.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("消费失败: %s", exc)
                await consumer.commit()
    finally:
        await consumer.stop()


async def main():
    if not cfg.kafka.enabled:
        logger.warning("KAFKA_BOOTSTRAP_SERVERS 未配置，消费端退出（无 Kafka）")
        return
    if not cfg.db.enabled:
        logger.error("Kafka 消费端依赖 MySQL 落库，请配置 DATABASE_URL")
        return

    db = build_db(cfg.db.url)
    db.create_all()
    from app.db.repo import TraceRepo

    repo = TraceRepo(db)
    logger.info("启动审计消费端: topics=%s group=%s", cfg.kafka.trace_topic, cfg.kafka.group_id)
    await consume_loop(repo)


if __name__ == "__main__":
    asyncio.run(main())