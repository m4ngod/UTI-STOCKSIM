import QtQuick 2.15

ResearchResourceBrowser {
    id: page
    objectName: "researchScenarioPage"
    required property var adapter
    title: "场景库"
    statusText: adapter === null ? "场景资源不可用" : adapter.statusMessage + " · " + adapter.freshness
    emptyMessage: adapter !== null && adapter.freshness === "fresh"
        && (adapter.presentationState === "ready" || adapter.presentationState === "empty")
        ? "当前没有可读取的旧场景、已批准版本或草稿。"
        : statusText
    limitationText: "旧资源兼容只读；类型未确认。不生成新场景，不修改已保存版本。场景构建与类型确认能力尚未接入。"
    entries: adapter === null ? [] : adapter.marketScenarios.map(function(item) {
        return {
            key: JSON.stringify(["market_scenario", item.scenarioId, item.recipeVersionId,
                item.recipeContentHash, item.pathId, item.segmentContentHash]),
            label: "旧场景 · " + item.scenarioId + "\n" + item.recipeVersionId,
            details: "市场场景: " + item.scenarioId
                + "\n类型未确认 · 兼容只读"
                + "\n原诊断层: " + item.layer + " · " + item.comparisonRole
                + "\n已批准配方版本: " + item.recipeVersionId
                + "\n种子: " + item.seed
                + "\n兼容性: " + item.compatibility
                + "\n可复现性: " + item.reproducibility
                + "\n执行条件解析: " + item.executionResolution
                + "\n" + item.unavailabilityReasons.map(function(reason) {
                    return reason.code + ": " + reason.summary + "\n" + reason.correctiveGuidance
                }).join("\n"),
            evidence: "配方内容哈希: " + item.recipeContentHash
                + "\n参考行情路径: " + item.pathId
                + "\n来源片段: " + item.segmentId
                + "\n片段内容哈希: " + item.segmentContentHash
                + "\n来源快照: " + item.sourceSnapshotId
                + "\n变换目录版本: " + item.transformationCatalogVersion
                + "\n市场规则版本: " + item.marketRuleProfileVersion
        }
    }).concat(adapter.approvedRecipeVersions.map(function(item) {
        return {
            key: JSON.stringify(["approved_recipe", item.recipeVersionId, item.contentHash]),
            label: "已批准版本 · " + item.name + "\n" + item.recipeVersionId,
            details: "已批准版本: " + item.recipeVersionId
                + "\n原配方: " + item.recipeId + " · v" + item.versionNumber
                + "\n名称: " + item.name
                + "\n内容哈希: " + item.contentHash
                + "\n批准记录: " + item.approvalId
                + "\n批准时间: " + item.approvedAt
                + "\n来源草稿: " + item.draftId + " · " + item.draftRevision
                + "\n校验记录: " + item.validationId
                + "\n依赖绑定可用: " + item.dependencyBindingAvailable
                + "\n来源片段: " + item.historicalSegmentId
                + "\n片段内容哈希: " + item.historicalSegmentContentHash
                + "\n来源快照: " + item.sourceSnapshotId
                + "\n权威状态: " + item.authorityState
                + "\n" + item.authorityReasons.map(function(reason) {
                    return reason.code + ": " + reason.summary + "\n" + reason.correctiveGuidance
                }).join("\n")
        }
    }), adapter.recipeDrafts.map(function(item) {
        return {
            key: JSON.stringify(["recipe_draft", item.draftId, item.revision, item.payloadHash]),
            label: "旧草稿 · " + item.name + "\n" + item.draftId + " · r" + item.revision,
            details: "旧草稿恢复资料，不是正式场景"
                + "\n草稿身份: " + item.draftId + " · r" + item.revision
                + "\n名称: " + item.name
                + "\n内容哈希: " + item.payloadHash
                + "\n创建时间: " + item.createdAt
                + "\n原配方: " + item.recipeId
                + "\n来源片段: " + item.historicalSegmentId
                + "\n前一草稿: " + (item.predecessorDraftId || "无")
                + "\n基于已批准版本: " + (item.basedOnRecipeVersionId || "无")
                + "\n当前仅提供精确修订的只读恢复资料，不自动批准、物化或运行。"
        }
    }))
}
