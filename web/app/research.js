/* Presentation metadata; returns and lifecycle decisions always come from the API. */
const QountResearch = (() => {
  function archived(line) { return line.research_status === "archived" || ["ARCHIVED", "STOPPED"].includes(line.status); }
  function available(line) { return !line.error && line.data_status === "AVAILABLE"; }
  function group(line) { return archived(line) ? "archived" : available(line) ? "available" : "waiting"; }
  function profile(line) {
    return { name: line.name || line.line_id, category: line.category || "其他", family: "独立研究",
      sample: line.sample_kind === "forward" ? "前向模拟" : "历史研究", method: "以来源中的研究说明为准。",
      note: line.adjudication || "结论待补充。", ...(line.presentation || {}) };
  }
  function dataState(line) {
    if (!available(line)) return { label: line.error || line.data_status === "ERROR" ? "来源不可用" : "来源未接入", tone: "missing" };
    if (line.paper_enabled === false || line.sample_kind === "historical") return { label: "历史样本", tone: "fresh" };
    if (line.freshness === "STALE") return { label: "数据待更新", tone: "stale" };
    if (line.freshness === "FRESH") return { label: "来源已更新", tone: "fresh" };
    return { label: "时点待确认", tone: "missing" };
  }
  function summary(lines) {
    return { all: lines.length, available: lines.filter(l => group(l) === "available").length,
      waiting: lines.filter(l => group(l) === "waiting").length,
      archived: lines.filter(archived).length,
      stale: lines.filter(l => available(l) && l.paper_enabled !== false && l.sample_kind !== "historical" && l.freshness === "STALE").length,
      missing: lines.filter(l => !available(l)).length };
  }
  function select(lines, filter = "all", query = "", category = "all") {
    const term = query.trim().toLocaleLowerCase();
    return lines.filter(line => (filter === "all" || group(line) === filter) &&
      (category === "all" || profile(line).category === category) &&
      [line.line_id, line.name, ...Object.values(profile(line))].join(" ").toLocaleLowerCase().includes(term));
  }
  return { profile, group, archived, available, dataState, summary, select };
})();
if (typeof module !== "undefined" && module.exports) module.exports = QountResearch;
