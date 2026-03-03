// 盲抽引擎（前端版）
// 目标：与 mapping/blind_draw_gui.py 的抽签逻辑保持一致（双重轮盘 + 分层卡池）

(function () {
  function toNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : NaN;
  }

  function normalizeBlindSafe(value) {
    // textMaterial.json 里常见为 "True"/"False" 字符串；也可能是 boolean/number
    if (value === true) return true;
    if (value === false) return false;
    if (typeof value === "string") {
      const v = value.trim().toLowerCase();
      if (v === "true" || v === "1" || v === "yes") return true;
      if (v === "false" || v === "0" || v === "no") return false;
      // 兼容其它非空字符串：按“有值”为真（与 Python truthy 更接近）
      return v.length > 0;
    }
    if (typeof value === "number") return value !== 0;
    return Boolean(value);
  }

  function weightedRandomChoice(pairs) {
    // pairs: Array<[item, weight]>
    let total = 0;
    for (const [, w] of pairs) total += w;
    if (!(total > 0)) throw new Error("权重总和必须大于 0");
    const r = Math.random() * total;
    let cumulative = 0;
    for (const [item, w] of pairs) {
      cumulative += w;
      if (cumulative > r) return item;
    }
    return pairs[pairs.length - 1][0];
  }

  function blindDrawOnce(items, reqKey) {
    const buckets = {
      SSR: [], // w >= 100
      SR: [],  // 80 <= w < 100
      R: [],   // 60 <= w < 80
      N: []    // 0 < w < 60
    };

    for (const item of items) {
      if (!normalizeBlindSafe(item && item.blind_safe)) continue;
      const mw = item && item.match_weights;
      if (!mw || typeof mw !== "object") continue;
      const raw = mw[reqKey];
      const w = toNumber(raw);
      if (!Number.isFinite(w) || w <= 0) continue;

      if (w >= 100) buckets.SSR.push(item);
      else if (w >= 80) buckets.SR.push(item);
      else if (w >= 60) buckets.R.push(item);
      else buckets.N.push(item);
    }

    const hasAny = buckets.SSR.length || buckets.SR.length || buckets.R.length || buckets.N.length;
    if (!hasAny) return null;

    const tierBaseWeights = {
      SSR: 75,
      SR: 15,
      R: 8,
      N: 2
    };

    const tierCandidates = [];
    for (const tier of ["SSR", "SR", "R", "N"]) {
      const list = buckets[tier];
      if (!list || list.length === 0) continue;
      const tw = tierBaseWeights[tier] || 0;
      if (tw > 0) tierCandidates.push([tier, tw]);
    }

    if (tierCandidates.length === 0) return null;

    const chosenTier = weightedRandomChoice(tierCandidates);
    const bucketItems = buckets[chosenTier] || [];
    if (bucketItems.length === 0) {
      const all = [...buckets.SSR, ...buckets.SR, ...buckets.R, ...buckets.N];
      if (all.length === 0) return null;
      return all[Math.floor(Math.random() * all.length)];
    }
    return bucketItems[Math.floor(Math.random() * bucketItems.length)];
  }

  window.BlindDrawEngine = {
    normalizeBlindSafe,
    blindDrawOnce
  };
})();

