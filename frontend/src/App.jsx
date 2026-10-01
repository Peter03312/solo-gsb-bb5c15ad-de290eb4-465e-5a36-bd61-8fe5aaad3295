import { useEffect, useMemo, useState } from "react";
import { fetchState, postConfirm, postPreview } from "./api";
import { findViolations, violationCellSet } from "./weave";
import "./styles.css";

const MAX_ROWS = 16;
const MAX_COLS = 8;

function cloneDesign(d) {
  return {
    rows: d.rows,
    cols: d.cols,
    k: d.k,
    grid: d.grid.map((row) => [...row]),
    locks: d.locks.map((p) => [...p]),
  };
}

function sortLocks(locks) {
  return [...locks].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

function sameDesign(a, b) {
  if (!a || !b) return false;
  if (a.rows !== b.rows || a.cols !== b.cols || a.k !== b.k) return false;
  for (let r = 0; r < a.rows; r += 1) {
    for (let c = 0; c < a.cols; c += 1) {
      if (a.grid[r][c] !== b.grid[r][c]) return false;
    }
  }
  const la = sortLocks(a.locks);
  const lb = sortLocks(b.locks);
  if (la.length !== lb.length) return false;
  return la.every((p, i) => p[0] === lb[i][0] && p[1] === lb[i][1]);
}

function validateDraft(d) {
  if (!Number.isInteger(d.rows) || d.rows < 1 || d.rows > MAX_ROWS) {
    return `行数必须是 1~${MAX_ROWS} 的整数`;
  }
  if (!Number.isInteger(d.cols) || d.cols < 1 || d.cols > MAX_COLS) {
    return `列数必须是 1~${MAX_COLS} 的整数`;
  }
  if (!Number.isInteger(d.k) || d.k < 1) return "最大浮长 K 必须是正整数";
  return null;
}

function lockSetOf(locks) {
  return new Set(locks.map(([r, c]) => `${r},${c}`));
}

/** 数字输入：失焦/回车时提交，非法输入还原并提示（拒绝非法编辑）。 */
function NumberField({ label, value, min, max, onCommit, onInvalid }) {
  const [text, setText] = useState(String(value));
  useEffect(() => { setText(String(value)); }, [value]);

  function commit() {
    const n = Number(text);
    if (Number.isInteger(n) && n >= min && n <= max) {
      if (n !== value) onCommit(n);
    } else {
      setText(String(value));
      onInvalid();
    }
  }

  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={text}
        min={min}
        max={max}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
      />
    </label>
  );
}

/** 织物组织网格。markOf(r, c, key) 返回附加样式名（violation / flipped）。 */
function WeaveGrid({ grid, lockSet, markOf, onCellClick, small }) {
  const cols = grid[0]?.length ?? 0;
  return (
    <div
      className={`weave-grid${small ? " small" : ""}${onCellClick ? "" : " readonly"}`}
      style={{ gridTemplateColumns: `repeat(${cols}, var(--cell))` }}
    >
      {grid.map((row, r) =>
        row.map((v, c) => {
          const key = `${r},${c}`;
          const locked = lockSet?.has(key);
          const mark = markOf ? markOf(r, c, key) : "";
          return (
            <button
              key={key}
              type="button"
              disabled={!onCellClick}
              className={`cell v${v}${locked ? " locked" : ""}${mark ? ` ${mark}` : ""}`}
              onClick={onCellClick ? () => onCellClick(r, c) : undefined}
              title={`第 ${r + 1} 行第 ${c + 1} 列 · ${v === 0 ? "0 经线在上" : "1 纬线在上"}${locked ? " · 已锁定" : ""}`}
            >
              <span className="val">{v}</span>
              {locked && <span className="badge">🔒</span>}
              {mark === "flipped" && <span className="badge flip">↺</span>}
            </button>
          );
        }))}
    </div>
  );
}

function ViolationList({ violations, k }) {
  if (violations.length === 0) {
    return <p className="ok-text">✓ 无超限段，当前稿件合法</p>;
  }
  return (
    <ul className="violation-list">
      {violations.map((v, i) => (
        <li key={i}>
          第 {v.index + 1} {v.kind === "row" ? "行" : "列"}：
          {v.length === null
            ? `全同为 ${v.value}（视为无限浮长）`
            : `环向连续 ${v.length} 个 ${v.value}`}
          ，超过 K={k}
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [original, setOriginal] = useState(null);
  const [draft, setDraft] = useState(null);
  const [mode, setMode] = useState("value");
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchState()
      .then((s) => { setOriginal(s); setDraft(cloneDesign(s)); })
      .catch((e) => setMessage({ type: "error", text: `加载原稿失败：${e.message}` }));
  }, []);

  const draftViolations = useMemo(
    () => (draft ? findViolations(draft.grid, draft.rows, draft.cols, draft.k) : []),
    [draft],
  );
  const draftViolationCells = useMemo(() => violationCellSet(draftViolations), [draftViolations]);
  const draftLockSet = useMemo(() => (draft ? lockSetOf(draft.locks) : new Set()), [draft]);

  const previewStale = Boolean(preview && draft && !sameDesign(draft, preview.input));
  const dirty = Boolean(original && draft && !sameDesign(draft, original));
  const canConfirm = Boolean(preview && preview.solvable && !previewStale && !busy);

  const flipSet = useMemo(
    () => new Set((preview?.flips ?? []).map(([r, c]) => `${r},${c}`)),
    [preview],
  );
  const previewLockSet = useMemo(
    () => (preview ? lockSetOf(preview.input.locks) : new Set()),
    [preview],
  );

  function handleCellClick(r, c) {
    setDraft((d) => {
      if (mode === "value") {
        const grid = d.grid.map((row, i) =>
          (i === r ? row.map((v, j) => (j === c ? 1 - v : v)) : row));
        return { ...d, grid };
      }
      const has = d.locks.some(([ir, ic]) => ir === r && ic === c);
      const locks = has
        ? d.locks.filter(([ir, ic]) => !(ir === r && ic === c))
        : sortLocks([...d.locks, [r, c]]);
      return { ...d, locks };
    });
  }

  function handleResize(rows, cols) {
    setDraft((d) => {
      const grid = Array.from({ length: rows }, (_, r) =>
        Array.from({ length: cols }, (_, c) =>
          (r < d.rows && c < d.cols ? d.grid[r][c] : 0)));
      const locks = d.locks.filter(([r, c]) => r < rows && c < cols);
      return { ...d, rows, cols, grid, locks };
    });
  }

  function fillAll(value) {
    setDraft((d) => ({
      ...d,
      grid: d.grid.map((row) => row.map(() => value)),
    }));
  }

  async function handlePreview() {
    const err = validateDraft(draft);
    if (err) {
      setMessage({ type: "error", text: err });
      return;
    }
    setBusy(true);
    try {
      const result = await postPreview(draft);
      setPreview(result);
      setMessage(result.solvable
        ? { type: "success", text: `预览成功：最少翻转 ${result.flipCount} 格，确认后覆盖原稿。` }
        : { type: "info", text: "无可行修补：已保留原稿，请调整稿件、锁定格或 K 后重试。" });
    } catch (e) {
      setPreview(null);
      setMessage({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!preview?.token) return;
    setBusy(true);
    try {
      const { state } = await postConfirm(preview.token, draft);
      setOriginal(state);
      setDraft(cloneDesign(state));
      setPreview(null);
      setMessage({ type: "success", text: "已确认当前预览并覆盖原稿，后续编辑基于新原稿。" });
    } catch (e) {
      setMessage({ type: "error", text: e.message });
      if (e.status === 409) setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  function handleReset() {
    setDraft(cloneDesign(original));
    setMessage({ type: "info", text: "草稿已还原为当前原稿。" });
  }

  if (!original || !draft) {
    return (
      <div className="page">
        {message && <div className={`banner ${message.type}`}>{message.text}</div>}
        <div className="loading">加载中…</div>
      </div>
    );
  }

  return (
    <div className="page">
      <header>
        <h1>周期平铺织物组织设计</h1>
        <p className="subtitle">
          0 = 经线在上，1 = 纬线在上；每行/每列的相同值连续段按环向（左右、上下边界相连）计，
          长度不得超过 K，全同的一行或一列视为无限浮长。
        </p>
      </header>

      {message && <div className={`banner ${message.type}`}>{message.text}</div>}

      <section className="toolbar">
        <NumberField
          label={`行数 (1~${MAX_ROWS})`} value={draft.rows} min={1} max={MAX_ROWS}
          onCommit={(n) => handleResize(n, draft.cols)}
          onInvalid={() => setMessage({ type: "error", text: `行数必须是 1~${MAX_ROWS} 的整数，已拒绝` })}
        />
        <NumberField
          label={`列数 (1~${MAX_COLS})`} value={draft.cols} min={1} max={MAX_COLS}
          onCommit={(n) => handleResize(draft.rows, n)}
          onInvalid={() => setMessage({ type: "error", text: `列数必须是 1~${MAX_COLS} 的整数，已拒绝` })}
        />
        <NumberField
          label="最大浮长 K" value={draft.k} min={1} max={Number.MAX_SAFE_INTEGER}
          onCommit={(n) => setDraft((d) => ({ ...d, k: n }))}
          onInvalid={() => setMessage({ type: "error", text: "最大浮长 K 必须是正整数，已拒绝" })}
        />

        <div className="mode-switch" role="group" aria-label="编辑模式">
          <button
            type="button"
            className={mode === "value" ? "active" : ""}
            onClick={() => setMode("value")}
          >
            编辑格值
          </button>
          <button
            type="button"
            className={mode === "lock" ? "active" : ""}
            onClick={() => setMode("lock")}
          >
            编辑锁定
          </button>
        </div>

        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={handlePreview}>
            预览修补
          </button>
          <button type="button" className="confirm" disabled={!canConfirm} onClick={handleConfirm}>
            确认应用预览
          </button>
          <button type="button" disabled={busy || !dirty} onClick={handleReset}>
            还原为原稿
          </button>
        </div>

        <div className="quick">
          <button type="button" onClick={() => fillAll(0)}>全部置 0</button>
          <button type="button" onClick={() => fillAll(1)}>全部置 1</button>
          <button type="button" onClick={() => setDraft((d) => ({ ...d, locks: [] }))}>
            清空锁定
          </button>
        </div>

        <span className={`dirty-flag ${dirty ? "yes" : ""}`}>
          {dirty ? "● 草稿有未确认修改" : "草稿与原稿一致"}
        </span>
      </section>

      <main>
        <section className="panel">
          <h2>草稿（点击格子{mode === "value" ? "翻转 0/1" : "加/解锁"}）</h2>
          <WeaveGrid
            grid={draft.grid}
            lockSet={draftLockSet}
            onCellClick={handleCellClick}
            markOf={(r, c, key) => (draftViolationCells.has(key) ? "violation" : "")}
          />
          <h3>超限段（{draftViolations.length}）</h3>
          <ViolationList violations={draftViolations} k={draft.k} />
        </section>

        <aside>
          <section className="panel">
            <h2>当前原稿 <span className="meta">v{original.version}</span></h2>
            <WeaveGrid grid={original.grid} lockSet={lockSetOf(original.locks)} small />
            <p className="meta">
              {original.rows} 行 × {original.cols} 列 · K={original.k} ·
              锁定 {original.locks.length} 格 · 超限段 {original.violations.length} 个
            </p>
            <ViolationList violations={original.violations} k={original.k} />
          </section>

          {preview && (
            <section className={`panel preview ${previewStale ? "stale" : ""}`}>
              <h2>修补预览 {previewStale && <span className="stale-tag">已失效</span>}</h2>
              {previewStale && (
                <p className="warn-text">
                  预览后草稿（交织格、锁定格或 K）已变动，旧预览失效，请重新预览。
                </p>
              )}
              {preview.solvable ? (
                <>
                  <WeaveGrid
                    grid={preview.repaired}
                    lockSet={previewLockSet}
                    markOf={(r, c, key) => (flipSet.has(key) ? "flipped" : "")}
                  />
                  <p className="meta">
                    最少翻转 {preview.flipCount} 格
                    {preview.flipCount > 0 && "（绿框 ↺ 为翻转位置）"}
                  </p>
                  {preview.flipCount > 0 && (
                    <ul className="flip-list">
                      {preview.flips.map(([r, c]) => (
                        <li key={`${r},${c}`}>
                          第 {r + 1} 行第 {c + 1} 列：
                          {preview.input.grid[r][c]} → {preview.repaired[r][c]}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <p className="warn-text">无可行修补：在锁定格约束下无法满足浮长限制，原稿保持不变。</p>
              )}
            </section>
          )}
        </aside>
      </main>

      <footer>
        <span className="legend-cell v0">0</span> 经线在上
        <span className="legend-cell v1">1</span> 纬线在上
        <span className="legend-cell locked">🔒</span> 锁定格（修补时不可翻转）
        <span className="legend-cell violation">0</span> 超限段
        <span className="legend-cell flipped">↺</span> 翻转位置
      </footer>
    </div>
  );
}
