import asyncio
import json
import logging
import time
from pathlib import Path

from app.config import cfg

logger = logging.getLogger("audit")


class JsonlProducer:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or cfg.audit_dir
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self) -> Path:
        return self.directory / f"audit_{time.strftime('%Y%m%d')}.jsonl"

    async def write(self, envelope: dict) -> None:
        line = json.dumps(envelope, ensure_ascii=False)
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with open(self._path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")


class AuditProducer:
    def __init__(self) -> None:
        self.jsonl = JsonlProducer()
        self.kafka = None
        self._queue: asyncio.Queue | None = None
        self._flusher: asyncio.Task | None = None
        self.kafka_failures = 0

        if cfg.kafka.enabled:
            try:
                from aiokafka import AIOKafkaProducer

                self._queue = asyncio.Queue(maxsize=1000)
                self.kafka = AIOKafkaProducer(
                    bootstrap_servers=cfg.kafka.bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                    max_request_size=1048576,
                )
                logger.info("审计 Producer = kafka (%s)", cfg.kafka.bootstrap_servers)
            except Exception as exc:  # noqa: BLE001
                logger.warning("aiokafka 不可用(%s)，审计降级为本地 JSONL", exc)
                self.kafka = None
        else:
            logger.info("审计 Producer = jsonl (Kafka 未配置)")

    async def start(self) -> None:
        if self.kafka is not None:
            await self.kafka.start()
            self._flusher = asyncio.create_task(self._flush_loop())

    async def publish(self, envelope: dict) -> None:
        if self.kafka is None or self._queue is None:
            await self.jsonl.write(envelope)
            return
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            await self.jsonl.write(envelope)

    def _topic_for(self, event_type: str) -> str:
        if event_type == "agent.tool.call":
            return cfg.kafka.tool_topic
        if event_type.startswith("security."):
            return cfg.kafka.security_topic
        return cfg.kafka.trace_topic

    async def _flush_loop(self) -> None:
        while True:
            envelope = await self._queue.get()
            topic = self._topic_for(envelope["event_type"])
            try:
                await self.kafka.send_and_wait(topic, value=envelope, key=envelope["event_id"].encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.kafka_failures += 1
                logger.warning("Kafka 发送失败(%s)，写入本地 JSONL: %s", exc, envelope["event_id"])
                await self.jsonl.write(envelope)

    async def close(self) -> None:
        if self._flusher is not None:
            self._flusher.cancel()
        if self.kafka is not None:
            await self.kafka.stop()