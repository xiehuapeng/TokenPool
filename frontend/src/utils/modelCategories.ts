export interface ModelCategory<T> {
  key: string;
  label: string;
  description: string;
  models: T[];
}

const QWEN_CATEGORY_META = [
  {
    key: "qwen-latest",
    label: "千问 3.5–3.8 文本/推理",
    description: "Qwen 3.5、3.6、3.7、3.8 的文本与推理模型",
  },
  {
    key: "qwen-text",
    label: "其他千问文本/推理",
    description: "千问通用、数学、搜索与旧版本文本模型",
  },
  {
    key: "coding",
    label: "代码模型",
    description: "Coder、CodeQwen 及其他代码专用模型",
  },
  {
    key: "multimodal",
    label: "视觉与多模态",
    description: "VL、Omni、OCR、QVQ 与 GUI 模型",
  },
  {
    key: "speech",
    label: "语音与音频",
    description: "ASR、TTS、Audio、实时语音与同传模型",
  },
  {
    key: "media",
    label: "图像与视频生成",
    description: "通义万相、Qwen Image 与视频生成模型",
  },
  {
    key: "embedding",
    label: "Embedding / Rerank",
    description: "向量化与重排模型",
  },
  {
    key: "third-party",
    label: "百炼托管第三方模型",
    description: "DeepSeek、GLM、Kimi、MiniMax、Mimo 等模型",
  },
  {
    key: "other",
    label: "平台工具与其他",
    description: "平台辅助、实验或尚未归入以上类别的模型",
  },
] as const;

function getModelId(model: Record<string, unknown>): string {
  return String(model.upstream_model || model.id || model.public_model || "");
}

function qwenCategoryKey(rawModelId: string): string {
  const modelId = rawModelId.toLowerCase();

  if (modelId.includes("embedding") || modelId.includes("rerank")) {
    return "embedding";
  }
  if (
    modelId.includes("coder") ||
    modelId.includes("codeqwen") ||
    /(?:^|[-_/])code(?:$|[-_/])/.test(modelId)
  ) {
    return "coding";
  }
  if (
    modelId.includes("audio") ||
    modelId.includes("asr") ||
    modelId.includes("tts") ||
    modelId.includes("speech") ||
    modelId.includes("s2s") ||
    modelId.includes("livetranslate")
  ) {
    return "speech";
  }
  if (
    modelId.includes("image") ||
    modelId.includes("video") ||
    modelId.startsWith("wan") ||
    modelId.startsWith("z-image")
  ) {
    return "media";
  }
  if (
    modelId.includes("-vl") ||
    modelId.includes("/vl") ||
    modelId.includes("omni") ||
    modelId.includes("ocr") ||
    modelId.startsWith("qvq") ||
    modelId.startsWith("gui-")
  ) {
    return "multimodal";
  }
  if (/^qwen3\.(?:5|6|7|8)(?:[-.]|$)/.test(modelId)) {
    return "qwen-latest";
  }
  if (
    modelId.startsWith("qwen") ||
    modelId.startsWith("qwq") ||
    modelId.startsWith("tongyi-")
  ) {
    return "qwen-text";
  }
  if (
    /^(?:deepseek|glm|kimi|kimi\/|minimax|minimax\/|siliconflow\/|vanchin\/|xiaomi\/|zhipu\/)/.test(
      modelId,
    )
  ) {
    return "third-party";
  }
  return "other";
}

export function categorizeProviderModels<T extends Record<string, unknown>>(
  providerCode: string,
  models: T[],
): ModelCategory<T>[] {
  if (providerCode !== "qwen") {
    return models.length
      ? [
          {
            key: "all",
            label: "全部模型",
            description: "当前 Provider 的全部模型",
            models,
          },
        ]
      : [];
  }

  const grouped = new Map<string, T[]>();
  for (const model of models) {
    const key = qwenCategoryKey(getModelId(model));
    const items = grouped.get(key) || [];
    items.push(model);
    grouped.set(key, items);
  }

  return QWEN_CATEGORY_META.flatMap((category) => {
    const items = grouped.get(category.key) || [];
    return items.length ? [{ ...category, models: items }] : [];
  });
}
