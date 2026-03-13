-- 001_event_log.sql
-- Spec: platform-hardening  Task:19  Requirement: Req2
-- 目的: 创建事件日志表用于回放 / 审计 / 恢复，以及可选的回放检查点表。
-- 兼容 SQLite 与 MySQL (方言无差异字段定义)。

/*==============================================================
  event_log 表
  字段说明:
    id       : 自增主键 (顺序播放辅助, 不等同于时间顺序但通常相关)
    ts_ms    : 事件时间戳 (毫秒) 用于排序/范围扫描
    type     : 事件类型 (与 core.const 中事件枚举对应)
    symbol   : 可为空, 针对单标的事件便于过滤
    payload  : JSON 文本 (若需要可在上层压缩 / 编码)
    shard    : 预留分片字段, 支持未来多实例写入拆分
==============================================================*/
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms BIGINT NOT NULL,
    type VARCHAR(64) NOT NULL,
    symbol VARCHAR(32),
    payload TEXT,
    shard INTEGER NOT NULL DEFAULT 0
);

-- 单列索引 (与 ORM 声明保持一致, 冪等创建)
CREATE INDEX IF NOT EXISTS ix_event_log_ts_ms ON event_log (ts_ms);
CREATE INDEX IF NOT EXISTS ix_event_log_type ON event_log (type);
CREATE INDEX IF NOT EXISTS ix_event_log_symbol ON event_log (symbol);
-- 复合索引: symbol + ts_ms 加速按标的时间范围回放
CREATE INDEX IF NOT EXISTS ix_event_log_symbol_ts ON event_log (symbol, ts_ms);

/*==============================================================
  event_log_checkpoint (可选)
  用途: 回放工具可将每个 shard 的回放进度写入; 若不需要可忽略。
  字段:
    shard      : 与 event_log.shard 对应
    last_ts_ms : 最近处理的时间戳
    last_id    : 最近处理的 id (补充定位)
    updated_at : 更新时间 (SQLite CURRENT_TIMESTAMP, MySQL 同样支持)
==============================================================*/
CREATE TABLE IF NOT EXISTS event_log_checkpoint (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shard INTEGER NOT NULL DEFAULT 0,
    last_ts_ms BIGINT,
    last_id BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_event_log_checkpoint_shard ON event_log_checkpoint (shard);

-- 使用指引:
-- 1. 执行此脚本后即可写入 EventPersistenceService 产生的事件。
-- 2. 回放: 按 (ts_ms, id) 升序扫描; 可附加 symbol 过滤或 shard 分段。
-- 3. 清理策略: 建议基于时间分区 (后续可扩展按日期拆表)。
-- 4. 若 MySQL: 可将 INTEGER PRIMARY KEY AUTOINCREMENT 替换为 BIGINT UNSIGNED AUTO_INCREMENT 视数据规模需要。

