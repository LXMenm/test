# Dashboard 与知识库联动现状审查报告

> 结论基于代码静态审查（前端 `app/src` + 后端 `app.py`/`event_store.py`/`knowledge_base`）。

## 1) Dashboard 结论
- 当前状态：**半动态**。
- 动态部分：Dashboard 前端会真实请求后端 `/api/stats/disease` 与 `/api/events`；后端统计由 `.cache/events/diagnosis_events.jsonl` 聚合而来。
- 缺失部分：没有总量、今日/近7天趋势、模型调用、个性化使用、追踪事件统计等指标；图表也只做了“Top病害横条 + 最近诊断列表”。

## 2) Dashboard 指标现状
- 病害 Top N（实际展示最多8条）：来源 `/api/stats/disease`，真实统计（JSONL聚合）。
- 最近诊断：来源 `/api/events`，真实读取事件日志。
- 详情面板：展示选中诊断项的病害、置信度、模型名、治疗文本/Top3。
- 未实现指标：总诊断次数、今日量、近7天趋势图、模型调用统计、个性化档案使用统计、trace事件统计。

## 3) Stats API 现状
- `GET /api/stats/disease`
  - 返回：`dict[str,int]`
  - 数据源：`event_store.stats_by_disease(_range)` → JSONL
  - 真实性：真实聚合
- `GET /api/stats/timeseries`
  - 返回：`[{date,count}]`
  - 数据源：JSONL
  - 真实性：真实聚合
  - 备注：前端 Dashboard 当前未消费
- `GET /api/stats/geo`
  - 返回：`[{lat,lon,disease,ts,image_url,confidence_pct}]`
  - 数据源：JSONL 中带经纬度事件
  - 真实性：真实聚合
  - 备注：前端 Dashboard 当前未消费

## 4) 诊断结果与统计联动
- 首轮诊断 `/api/diagnose-image` 完成后会构建 event 并 `append_event(event)` 落盘 JSONL。
- Dashboard 在进入页面时请求一次数据，支持手动刷新按钮。
- 因此统计更新机制是：**完成诊断后，刷新 Dashboard（或手动点刷新）可见更新**。
- 非实时推送（无 SSE/WebSocket 到 Dashboard）。
- 二次确认接口 `/api/diagnose-confirm` 没有写入 `append_event`，确认轮次不进入统计。

## 5) 知识库联动现状
- KB 页面是管理页：支持四类数据（病害、治疗、规则、症状映射）的列表、搜索、批量删除、弹窗编辑/新增（CRUD）。
- 诊断结果页未把病害名做成可点击链接；前端路由也只有 `/kb`，无 `/kb/:id` 详情页。
- 后端也没有 `GET /api/kb/diseases/{name}` 详情接口（仅列表 + 管理接口）。
- 诊断返回结构没有 `disease_id/slug/knowledge_ref/kb_snapshot` 这类前端可直接跳转字段。
- 检索智能体内部确实构建了 `kb_snapshot` 并供治疗智能体使用，但该快照未下发给诊断结果页进行跳转复用。

## 6) 优先级问题
- P0：诊断页与 KB 页没有跳转闭环（病害不可点、无详情路由、无详情接口）。
- P0：Dashboard 指标覆盖不足，无法体现“管理系统”运营视角。
- P1：二次确认结果未写事件，统计口径不完整。
- P1：前端 Dashboard 未消费已存在的 `timeseries/geo` API。
- P2：Dashboard 对 stats 返回结构做了宽松兼容，虽健壮但可能掩盖接口契约漂移。

## 7) 最小闭环改造路线（不改架构）
1. **先打通知识跳转闭环**：
   - 后端补 `GET /api/kb/diseases/{name}`；
   - 前端加 `/kb/:name` 详情视图（可在现有KB页内按 query 或路由切换实现）；
   - 诊断结果中的 `final_disease` 与 Top3 病害改为可点击跳转。
2. **补齐 Dashboard 最小运营指标**：
   - 前端接入 `/api/stats/timeseries`（近7/30天折线或柱状）；
   - 增加总诊断次数、今日诊断数（可由 events/timeseries聚合）；
   - 增加模型调用分布（从 event.meta.model_id 统计）。
3. **统一事件口径**：
   - `/api/diagnose-confirm` 也写入事件（含 confirm_round 标识）；
   - Dashboard 可选择是否合并首轮+确认轮，或分层展示。

## 8) 高风险误判点
- 看起来“有 stats API”不代表前端都用了：目前 Dashboard 实际只用了 disease/events。
- 检索智能体“有 kb_snapshot”不代表前端有闭环：该数据只在后端智能体链路中使用。
- 页面有 KB CRUD 不代表“诊断联动已完成”：缺少结果页链接/详情路由/详情接口。
