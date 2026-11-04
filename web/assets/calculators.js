/*
 * 免費試算工具：所有計算都在使用者的瀏覽器內完成，不傳送任何數字。
 * 為避免浮點誤差，金額以 BigInt 有理數（分子／分母）計算。
 * 顯示用數字「四捨五入」到小數兩位；最低售價一律「無條件進位」到小數兩位。
 * 本檔沒有任何網路請求，也不使用 cookie 或任何瀏覽器儲存。
 */
(function (root) {
  "use strict";

  var DECIMAL = /^[+-]?\d+(\.\d+)?$/;
  var MAX_QUANTITIES = 20;

  function gcd(a, b) { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { var t = a % b; a = b; b = t; } return a || 1n; }
  function frac(n, d) { if (d < 0n) { n = -n; d = -d; } var g = gcd(n, d); return { n: n / g, d: d / g }; }
  function add(a, b) { return frac(a.n * b.d + b.n * a.d, a.d * b.d); }
  function sub(a, b) { return frac(a.n * b.d - b.n * a.d, a.d * b.d); }
  function mul(a, b) { return frac(a.n * b.n, a.d * b.d); }
  function div(a, b) { if (b.n === 0n) throw new Error("不能除以 0"); return frac(a.n * b.d, a.d * b.n); }
  function cmp(a, b) { var x = a.n * b.d - b.n * a.d; return x === 0n ? 0 : (x > 0n ? 1 : -1); }
  var ZERO = { n: 0n, d: 1n }, ONE = { n: 1n, d: 1n }, HUNDRED = { n: 100n, d: 1n };

  function parse(value, label) {
    var text = String(value === undefined || value === null ? "" : value).trim().replace(/,/g, "");
    if (!DECIMAL.test(text)) throw new Error("「" + label + "」請輸入數字（例如 180 或 12.5）");
    var neg = text[0] === "-";
    text = text.replace(/^[+-]/, "");
    var parts = text.split(".");
    var decimals = parts[1] ? parts[1].length : 0;
    var n = BigInt(parts[0] + (parts[1] || ""));
    return frac(neg ? -n : n, 10n ** BigInt(decimals));
  }

  function nonNegative(value, label) {
    var x = parse(value, label);
    if (cmp(x, ZERO) < 0) throw new Error("「" + label + "」不可為負數");
    return x;
  }

  function positive(value, label) {
    var x = parse(value, label);
    if (cmp(x, ZERO) <= 0) throw new Error("「" + label + "」必須大於 0");
    return x;
  }

  function percent(value, label, allowHundred) {
    var x = parse(value, label);
    if (cmp(x, ZERO) < 0 || (allowHundred ? cmp(x, HUNDRED) > 0 : cmp(x, HUNDRED) >= 0)) {
      throw new Error("「" + label + "」必須介於 0（含）與 100（不含）之間");
    }
    return div(x, HUNDRED);
  }

  // 四捨五入（離零方向）到小數兩位
  function roundHalfUp(x) {
    var scaled = x.n * 100n, d = x.d, neg = scaled < 0n;
    if (neg) scaled = -scaled;
    var q = scaled / d, r = scaled % d;
    if (r * 2n >= d) q += 1n;
    return format(neg ? -q : q);
  }

  // 無條件進位到小數兩位（往正無限大方向）
  function ceilCents(x) {
    var scaled = x.n * 100n, d = x.d;
    var q = scaled / d;
    if (scaled % d !== 0n && scaled > 0n) q += 1n;
    return format(q);
  }

  function format(cents) {
    var neg = cents < 0n;
    if (neg) cents = -cents;
    var s = cents.toString().padStart(3, "0");
    return (neg && cents !== 0n ? "-" : "") + s.slice(0, -2) + "." + s.slice(-2);
  }

  function quantities(text) {
    var items = String(text || "").split(/[,，\s]+/).filter(function (s) { return s !== ""; });
    if (!items.length) throw new Error("請輸入至少一個數量");
    if (items.length > MAX_QUANTITIES) throw new Error("一次最多 " + MAX_QUANTITIES + " 個數量");
    var seen = {};
    return items.map(function (s) {
      if (!/^\d+$/.test(s) || BigInt(s) === 0n) throw new Error("數量「" + s + "」必須是正整數");
      if (seen[s]) throw new Error("數量不可重複");
      seen[s] = true;
      return Number(s);
    }).sort(function (a, b) { return a - b; });
  }

  // 1. 成本增加百分比
  function costIncrease(oldCost, newCost) {
    var o = positive(oldCost, "原成本"), n = nonNegative(newCost, "新成本");
    var diff = sub(n, o);
    return { difference: roundHalfUp(diff), percent: roundHalfUp(mul(div(diff, o), HUNDRED)) };
  }

  // 2. 毛利率與加價率
  function marginMarkup(cost, price) {
    var c = positive(cost, "成本"), p = positive(price, "售價");
    var profit = sub(p, c);
    return { margin: roundHalfUp(mul(div(profit, p), HUNDRED)), markup: roundHalfUp(mul(div(profit, c), HUNDRED)) };
  }

  function marginToMarkup(marginPercent) {
    var m = percent(marginPercent, "毛利率", false);
    return roundHalfUp(mul(div(m, sub(ONE, m)), HUNDRED));
  }

  function markupToMargin(markupPercent) {
    var k = div(nonNegative(markupPercent, "加價率"), HUNDRED);
    return roundHalfUp(mul(div(k, add(ONE, k)), HUNDRED));
  }

  // 3. 批次固定費分攤
  function batchAllocation(variable, fixed, qty) {
    var v = nonNegative(variable, "單件變動成本"), f = nonNegative(fixed, "每批固定費");
    var q = quantities(qty);
    if (q.length !== 1) throw new Error("請輸入一個數量");
    var share = div(f, { n: BigInt(q[0]), d: 1n });
    return { fixedPerPiece: roundHalfUp(share), costPerPiece: roundHalfUp(add(v, share)) };
  }

  // 4. 數量階梯最低售價（無條件進位）
  function quantityTiers(variable, fixed, marginPercent, qtyText, moq) {
    var v = nonNegative(variable, "單件變動成本"), f = nonNegative(fixed, "每批固定費");
    var m = percent(marginPercent, "目標毛利率", false);
    var minQty = (moq === undefined || moq === null || String(moq).trim() === "") ? null : quantities(moq)[0];
    return quantities(qtyText).map(function (q) {
      if (minQty !== null && q < minQty) {
        return { quantity: q, status: "低於最低訂購量", costPerPiece: null, floor: null };
      }
      var cost = add(v, div(f, { n: BigInt(q), d: 1n }));
      return { quantity: q, status: "可試算", costPerPiece: roundHalfUp(cost), floor: ceilCents(div(cost, sub(ONE, m))) };
    });
  }

  var api = { costIncrease: costIncrease, marginMarkup: marginMarkup, marginToMarkup: marginToMarkup,
              markupToMargin: markupToMargin, batchAllocation: batchAllocation, quantityTiers: quantityTiers };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.Calculators = api; }
})(this);
