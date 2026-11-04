/* 將計算結果顯示在頁面上。只操作本頁 DOM，不傳送任何資料。 */
(function () {
  "use strict";
  var C = window.Calculators;
  function val(id) { return document.getElementById(id).value; }
  function show(id, build) {
    var box = document.getElementById(id);
    box.textContent = "";
    try { build(box); } catch (e) {
      var p = document.createElement("p"); p.className = "error"; p.textContent = e.message; box.appendChild(p);
    }
  }
  function line(box, text) { var p = document.createElement("p"); p.textContent = text; box.appendChild(p); }
  var tools = {
    cost: function () {
      show("ci-result", function (box) {
        var r = C.costIncrease(val("ci-old"), val("ci-new"));
        line(box, "每件成本增加：" + r.difference + " 元（" + r.percent + "%）");
      });
    },
    margin: function () {
      show("mm-result", function (box) {
        var r = C.marginMarkup(val("mm-cost"), val("mm-price"));
        line(box, "毛利率：" + r.margin + "%　加價率：" + r.markup + "%");
        if (val("mm-margin").trim()) line(box, "毛利率 " + val("mm-margin") + "% ＝ 加價率 " + C.marginToMarkup(val("mm-margin")) + "%");
        if (val("mm-markup").trim()) line(box, "加價率 " + val("mm-markup") + "% ＝ 毛利率 " + C.markupToMargin(val("mm-markup")) + "%");
      });
    },
    batch: function () {
      show("ba-result", function (box) {
        var r = C.batchAllocation(val("ba-var"), val("ba-fixed"), val("ba-qty"));
        line(box, "每件分攤固定費：" + r.fixedPerPiece + " 元　每件成本：" + r.costPerPiece + " 元");
      });
    },
    tiers: function () {
      show("qt-result", function (box) {
        var rows = C.quantityTiers(val("qt-var"), val("qt-fixed"), val("qt-margin"), val("qt-qty"), val("qt-moq"));
        var wrap = document.createElement("div"); wrap.className = "table-scroll";
        var table = document.createElement("table");
        var head = table.insertRow();
        ["數量", "每件成本", "最低售價（試算）", "狀態"].forEach(function (h) {
          var th = document.createElement("th"); th.textContent = h; head.appendChild(th);
        });
        rows.forEach(function (r) {
          var tr = table.insertRow();
          [r.quantity, r.costPerPiece || "—", r.floor || "—", r.status].forEach(function (v, i) {
            var td = tr.insertCell(); td.textContent = v; if (i < 3) td.className = "num";
          });
        });
        wrap.appendChild(table); box.appendChild(wrap);
        line(box, "最低售價已無條件進位；這只是成本與毛利目標的下限，不是正式報價。");
      });
    }
  };
  Array.prototype.forEach.call(document.querySelectorAll("[data-tool]"), function (btn) {
    btn.addEventListener("click", tools[btn.getAttribute("data-tool")]);
  });
})();
