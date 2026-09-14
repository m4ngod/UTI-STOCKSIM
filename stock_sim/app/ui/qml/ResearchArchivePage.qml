import QtQuick 2.15

ResearchResourceBrowser {
    required property var adapter
    objectName: "researchArchivePage"
    title: "实验档案"
    statusText: adapter === null ? "实验档案资源不可用" : adapter.statusText
    entries: adapter === null ? [] : adapter.researchEvidenceResources
    limitationText: "当前为精确来源的旧证据兼容视图；跨实验统计尚未接入，不生成矩阵、排名或新指标。不自动选择其他运行，也不把部分证据当作完整结果。"
}
