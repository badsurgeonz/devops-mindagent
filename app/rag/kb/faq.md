# DevOps 故障排查手册（示例知识库）

## 一、服务 500 / StackTrace 定位

症状：接口返回 500，网关日志出现 `500 Internal Server Error`，业务日志打印堆栈。

排查步骤：

1. 先定位报错服务名与时间窗口，检索 `error` / `exception` / `stacktrace` 关键字。
2. 若堆栈包含 `redis.clients.jedis.exceptions.JedisConnectionException`，通常为 Redis 连接池耗尽或实例不可达。
3. 若堆栈包含 `MySQLSyntaxErrorException` 或 `Deadlock`，关注 SQL 慢查询与锁等待。
4. 修复后观察错误数是否回落，必要时回滚最近一次发布。

## 二、Redis 连接池耗尽与超时

症状：`Could not get a resource from the pool`、`SocketTimeoutException: Read timed out`、客户端大量连接报错。

排查步骤：

1. 查看 `connected_clients`、`used_memory_human`、`blocked_clients` 指标。
2. 检查是否存在大 Key（单 Key > 1MB 或 > 10000 个元素），大 Key 会阻塞单线程执行。
3. 调大连接池 `maxTotal` 不能根治，需排查慢命令与热 Key。
4. 命令建议：`redis-cli --bigkeys`、`MONITOR`（谨慎用于低峰期）。

## 三、缓存雪崩 / 穿透 / 击穿

雪崩：大量 Key 同一时间过期，请求直达数据库。

- 解决方案：过期时间加随机抖动、多级缓存、熔断降级。

穿透：查询不存在的 Key，请求直接打穿到数据库。

- 解决方案：缓存空值 + 短 TTL、布隆过滤器前置拦截。

击穿：单个热点 Key 过期瞬间高并发同时重建。

- 解决方案：互斥锁重建、逻辑过期、热点 Key 不过期 + 后台更新。

## 四、MySQL 慢查询与锁等待

症状：`Lock wait timeout exceeded`、CPU 飙高、接口 RT 上涨。

排查步骤：

1. `SHOW FULL PROCESSLIST` 观察长时间运行的 SQL。
2. `EXPLAIN` 分析是否走索引，避免 `SELECT *` 与全表扫描。
3. 关注慢查询日志：`long_query_time` 建议 1s。
4. 分批提交事务，避免长事务持有行锁。

## 五、Kafka 消费积压

症状：消费者 lag 持续增长，消息延迟处理。

排查步骤：

1. 查看各分区消费位点与 `consumer lag`。
2. 若为单线程消费导致积压，增加分区与消费者实例并行度。
3. 下游 Redis/MySQL 出现瓶颈时，先扩容下游，再追位点。
4. 升级消费失败需确认是否进入重试死信队列。

## 六、应用内存 OOM

症状：`java.lang.OutOfMemoryError: Java heap space`、容器被 OOMKilled 重启。

排查步骤：

1. 拉取堆转储（`jmap -dump`），分析大对象与泄漏点。
2. 关注缓存组件未设上限、批量查询加载全量数据等常见问题。
3. 设置合理的 `-Xmx` 与堆外内存，容器内存需留出余量。

## 七、发布与回滚规范

- 发布前：检查变更清单、依赖兼容性、数据库变更是否兼容。
- 发布后：观察错误率、RT、GC 与依赖服务健康度 10 分钟。
- 出现严重故障：优先回滚而非线上调试，回滚遵循一键回滚流程。