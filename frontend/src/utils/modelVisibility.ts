const legacyFlashIds = new Set([
  "deepseek-v4-flash",
  "deepseek-v4-flash-vision-exp",
]);

export function displayedModelId(id: string | null | undefined): string {
  return id && legacyFlashIds.has(id) ? "deepseek-flash" : id || "";
}

export function visibleUserModels<T extends { id: string; selected?: boolean }>(
  models: T[],
): T[] {
  const selected = models.find((model) => model.selected)?.id;
  return models
    .filter((model) => !legacyFlashIds.has(model.id))
    .map((model) => ({
      ...model,
      selected:
        model.selected ||
        (model.id === "deepseek-flash" && displayedModelId(selected) === model.id),
    }));
}
