"""AgentCreationController (Spec Task 21)

职责:
- 批量创建仅限 Retail / MultiStrategyRetail (调用 AgentService.batch_create_retail)
- 对不支持类型的请求抛出原始 AgentServiceError
- 新增 (R2/T5): 批量���建进度/取消/并发控制与事件发布
"""
from __future__ import annotations
from typing import Dict, Any, Optional, Callable, List
from threading import RLock, Thread
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
import time
import uuid

from app.services.agent_service import AgentService, BatchCreateConfig, AgentServiceError, BATCH_ALLOWED_TYPES
from infra.event_bus import event_bus
from observability.metrics import metrics
from observability.struct_logger import logger

__all__ = ["AgentCreationController"]

ProgressCallback = Callable[[Dict[str, Any]], None]

class AgentCreationController:
    def __init__(self, service: AgentService):
        self._service = service
        self._lock = RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._executors: Dict[str, ThreadPoolExecutor] = {}

    # ---------------- 兼容旧接口 ----------------
    def batch_create(self, *, agent_type: str, count: int, name_prefix: str = "agent") -> Dict[str, Any]:
        if agent_type not in BATCH_ALLOWED_TYPES:
            # 与规范保持: 非允许类型直接抛出业务错误
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {agent_type} not allowed for batch")
        cfg = BatchCreateConfig(count=count, agent_type=agent_type, name_prefix=name_prefix)
        return self._service.batch_create_retail(cfg)

    # ---------------- 新增: 带进度/取消的批量创建 ----------------
    def batch_create_multi_strategy(self,
                                    *,
                                    count: int,
                                    capital: Optional[float] = None,  # 预留
                                    strategy: Optional[str] = None,    # 预留
                                    seed: Optional[int] = None,        # 预留
                                    name_prefix: str = "agent",
                                    agent_type: str = "MultiStrategyRetail",
                                    chunk_size: int = 20,
                                    concurrency: int = 2,
                                    job_id: Optional[str] = None,
                                    progress_callback: Optional[ProgressCallback] = None,
                                    progress_topic: str = "agent.batch.create.progress",
                                    completed_topic: str = "agent.batch.create.completed",
                                    ) -> Dict[str, Any]:
        if agent_type not in BATCH_ALLOWED_TYPES:
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {agent_type} not allowed for batch")
        if count <= 0:
            raise AgentServiceError("INVALID_COUNT", "count must be positive")
        chunk = max(1, int(chunk_size))
        conc = max(1, int(concurrency))
        jid = job_id or str(uuid.uuid4())
        with self._lock:
            if jid in self._jobs:
                # 幂等: 返回现有任务状态
                return {"job_id": jid, "status": self._status_locked(jid)}
            # 初始化任务状态
            self._jobs[jid] = {
                "job_id": jid,
                "agent_type": agent_type,
                "name_prefix": name_prefix,
                "count": int(count),
                "chunk_size": chunk,
                "concurrency": conc,
                "success_ids": [],
                "failed": [],
                "scheduled": 0,
                "completed": 0,
                "cancel_requested": False,
                "done": False,
                "error": None,
                "started_ts": time.time(),
                "completed_ts": None,
            }
            self._executors[jid] = ThreadPoolExecutor(max_workers=conc, thread_name_prefix=f"AgentBatch-{jid[:8]}")
        # 启动调度线程
        Thread(target=self._run_job, args=(jid, progress_callback, progress_topic, completed_topic), daemon=True).start()
        return {"job_id": jid, "status": self.get_job_status(jid)}

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.get("done"):
                return True
            job["cancel_requested"] = True
            logger.log("agent.batch.cancel_requested", job_id=job_id)
            return True

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._status_locked(job_id)

    # ---------------- 内部实现 ----------------
    def _status_locked(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "JOB_NOT_FOUND"}
        # 复制主要可见字段
        return {
            "job_id": job_id,
            "count": job["count"],
            "completed": job["completed"],
            "scheduled": job["scheduled"],
            "success": len(job["success_ids"]),
            "failed": len(job["failed"]),
            "cancel_requested": job["cancel_requested"],
            "done": job["done"],
            "error": job["error"],
            "started_ts": job["started_ts"],
            "completed_ts": job["completed_ts"],
        }

    def _run_job(self, job_id: str, progress_callback: Optional[ProgressCallback], progress_topic: str, completed_topic: str):
        try:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                chunk = job["chunk_size"]
                agent_type = job["agent_type"]
                name_prefix = job["name_prefix"]
                executor = self._executors[job_id]
                conc = job["concurrency"]
                remaining = job["count"]
            in_flight: List[Future] = []
            # 调度—执行循环（限并发，可随时取消）
            while remaining > 0 or in_flight:
                # 若可调度，补足到并发上限
                with self._lock:
                    cancel = self._jobs.get(job_id, {}).get("cancel_requested", False)
                while remaining > 0 and len(in_flight) < conc and not cancel:
                    n = min(chunk, remaining)
                    with self._lock:
                        if self._jobs.get(job_id, {}).get("cancel_requested", False):
                            cancel = True
                            break
                        self._jobs[job_id]["scheduled"] += n
                    in_flight.append(executor.submit(self._do_batch_call, job_id, agent_type, n, f"{name_prefix}"))
                    remaining -= n
                if not in_flight:
                    # 无在途任务，可能因取消导致未满额即退出
                    break
                done, _ = wait(in_flight, timeout=0.5, return_when=FIRST_COMPLETED)
                # 处理已完成分块
                for fut in list(done):
                    in_flight.remove(fut)
                    try:
                        res = fut.result()
                        self._on_chunk_done(job_id, res, progress_callback, progress_topic)
                    except AgentServiceError as e:
                        self._on_chunk_fail(job_id, e, progress_callback, progress_topic)
                    except Exception as e:  # noqa: BLE001
                        self._on_chunk_fail(job_id, AgentServiceError("UNKNOWN", str(e)), progress_callback, progress_topic)
            # 结束
            with self._lock:
                j = self._jobs.get(job_id)
                if j is None:
                    return
                j["done"] = True
                j["completed_ts"] = time.time()
                st = self._status_locked(job_id)
            event_bus.publish(completed_topic, {"job_id": job_id, "status": st})
            metrics.inc("agent_batch_completed")
            logger.log("agent.batch.completed", job_id=job_id, status=st)
        finally:
            # 关闭执行器
            with self._lock:
                ex = self._executors.pop(job_id, None)
            try:
                if ex:
                    ex.shutdown(wait=False, cancel_futures=False)
            except Exception:
                pass

    def _do_batch_call(self, job_id: str, agent_type: str, n: int, name_prefix: str) -> Dict[str, Any]:
        # 若期间收到取消请求，尽早结束（最佳努力）
        with self._lock:
            if self._jobs.get(job_id, {}).get("cancel_requested"):
                raise AgentServiceError("CANCELED", "job canceled")
        cfg = BatchCreateConfig(count=n, agent_type=agent_type, name_prefix=name_prefix)
        res = self._service.batch_create_retail(cfg)
        return res

    def _on_chunk_done(self, job_id: str, res: Dict[str, Any], progress_callback: Optional[ProgressCallback], progress_topic: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            succ: List[str] = list(res.get("success_ids", []))
            fail: List[str] = list(res.get("failed", []))
            job["success_ids"].extend(succ)
            job["failed"].extend(fail)
            job["completed"] += len(succ) + len(fail)
            st = self._status_locked(job_id)
        # 新增：成功/失败计数指标（创建成功率可由外部聚合计算）
        try:
            if succ:
                metrics.inc("agent_create_success", len(succ))
            if fail:
                metrics.inc("agent_create_failed", len(fail))
        except Exception:
            pass
        # 发布进度
        event_bus.publish(progress_topic, {"job_id": job_id, "status": st})
        if progress_callback:
            try:
                progress_callback(st)
            except Exception:
                pass
        metrics.inc("agent_batch_progress")

    def _on_chunk_fail(self, job_id: str, err: AgentServiceError, progress_callback: Optional[ProgressCallback], progress_topic: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["error"] = err.code
            # 将本分块记为失败 N（无法得知具体id，聚合错误码）
            st = self._status_locked(job_id)
        event_bus.publish(progress_topic, {"job_id": job_id, "status": st, "error": {"code": err.code, "message": err.message}})
        if progress_callback:
            try:
                progress_callback(st)
            except Exception:
                pass
        metrics.inc("agent_batch_error")
        logger.log("agent.batch.chunk_error", job_id=job_id, code=err.code, message=err.message)
