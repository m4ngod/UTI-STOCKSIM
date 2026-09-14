import QtQuick 2.15

ResearchResourceBrowser {
    required property var adapter
    objectName: "researchLabPage"
    title: "实验室"
    statusText: adapter === null ? "实验室任务资源不可用" : adapter.statusText
    emptyMessage: adapter !== null && !adapter.hasRequestedTask
        ? "尚未选择旧任务；不会自动选择其他任务。\n" + statusText
        : statusText
    entries: adapter === null ? [] : adapter.researchTaskResources
    limitationText: "当前显示明确选中的旧任务及配置，只读观察，不自动创建实验。实验创建、完整列表与精确 Attempt 控制尚未接入。没有选中的旧任务时不擅自选择其他任务。"
}
