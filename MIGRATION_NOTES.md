# Migration Notes — 三層記憶架構改造

> 改動日期：2026-05-26
> 改動者：Claude Code

---

## 改動摘要

### 新增文件
| 文件 | 用途 |
|------|------|
| `raw_memory_store.py` | 原話保留層（SQLite append-only） |
| `migrate_raw_backfill.py` | 把現有桶的 content 回填到 raw 層 |
| `tests/test_subject_integrity.py` | 主語完整性測試（4 個案例） |
| `MIGRATION_NOTES.md` | 本文件 |

### 修改文件
| 文件 | 改動 |
|------|------|
| `server.py` | ① hold 新增 actor/target/action 參數 ② 新增 recall MCP 工具 ③ breath 搜索模式 raw 層優先 ④ _merge_or_create 收緊合併規則 ⑤ grow 存 raw |
| `dehydrator.py` | ① DEHYDRATE_PROMPT 加主語保留規則 ② MERGE_PROMPT 加主語保留規則 ③ ANALYZE_PROMPT 加 actor/target/action 輸出 ④ 新增 _validate_dehydration 驗證層 ⑤ 新增 PEOPLE_CANONICAL_LIST |
| `bucket_manager.py` | create/update 支持 actor/target/action 欄位寫入 YAML frontmatter |

---

## 架構變化

```
Before:
  Claude ←→ MCP ←→ server.py ←→ bucket_manager (桶) + dehydrator (摘要)

After:
  Claude ←→ MCP ←→ server.py
                      │
         ┌────────────┼────────────────┐
         │            │                │
   raw_memory_store  bucket_manager  dehydrator
   (原話·不可改)     (桶·可合併)     (摘要·有驗證)
```

### 三層記憶結構
1. **Raw 層**（`raw_memories.db`）：原話完整保留，append-only，永不修改
2. **Bucket 層**（Markdown 文件）：可合併、可衰減的結構化記憶
3. **Summary 層**（dehydration cache）：展示用的壓縮摘要

---

## 新增 MCP 工具

| 工具 | 用途 |
|------|------|
| `recall(query, limit)` | 直接搜索原話層，返回原始完整內容 |

---

## Hold 工具新增參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `actor` | str | 動作發出者（如「番茄」） |
| `target` | str | 動作接收者（如「小汐」） |
| `action` | str | 核心動作（如「說」「送」「哭」） |

未填時由 dehydrator.analyze 自動推斷。

---

## Merge 規則變化

### 新增阻斷條件（永不合併）：
- `importance >= 8`
- 目標桶 `importance >= 8`
- 目標桶為 `feel` 類型
- `domain` 屬於 `{"核心准则", "人設", "身份"}`
- **主語衝突**：新記憶的 actor 與目標桶的 actor 不同 → 拒絕合併
- **對象衝突**：新記憶的 target 與目標桶的 target 不同 → 拒絕合併

### 原有保留的阻斷：
- 目標桶為 `pinned` / `protected`

---

## Dehydrator 變化

### Prompt 強制規則：
- 專有名詞（小汐、番茄、奶凍卷、尼莫、媽媽）不可代詞化
- 每句主語必須明確
- 引號內的直接引語一字不差保留
- 不合併不同人物的話/動作

### 驗證層（_validate_dehydration）：
- 脫水後比對人名集合 vs 原文人名集合
- 出現原文沒有的人名 → reject + retry（最多 2 次）
- 原文人名在摘要中消失 → reject + retry
- 兩次失敗 → 用原文代替摘要（容錯）

---

## 數據遷移

### 步驟：
```bash
# 1. 預覽（不寫入）
python migrate_raw_backfill.py --dry-run

# 2. 正式執行
python migrate_raw_backfill.py
```

### 產生的文件：
- `{buckets_dir}/raw_memories.db` — 原話保留層 SQLite 資料庫

---

## 回滾方法

如果需要回退此改動：

1. **恢復代碼**：`git revert <commit-hash>` 或 checkout 到之前的版本
2. **刪除 raw_memories.db**：`rm buckets/raw_memories.db`（raw 層是新增的，刪除不影響原有功能）
3. **桶文件中的 actor/target/action**：這些是新增欄位，舊代碼會忽略它們，無需刪除

回滾後不會丟失任何原有數據。所有改動都是**增量的**：
- 新增了一個 SQLite 資料庫
- 桶 frontmatter 多了 3 個可選欄位
- 原有的雙通道檢索、衰減曲線、dream/feel 機制完全不受影響

---

## 配置變化

### config.yaml 新增可選鍵：
```yaml
# 人物正規名列表（用於 merge 主語衝突檢測）
people_canonical_list:
  - 小汐
  - 番茄
  - 奶凍卷
  - 尼莫
  - 媽媽
```

不配置也能用，默認使用 dehydrator.py 中的 PEOPLE_CANONICAL_LIST。

---

## 測試

```bash
# 主語完整性測試
python tests/test_subject_integrity.py

# 原有測試
python test_tools.py
python test_smoke.py
```
