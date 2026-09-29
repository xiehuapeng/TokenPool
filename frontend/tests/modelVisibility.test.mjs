import assert from "node:assert/strict";
import test from "node:test";
import { displayedModelId, visibleUserModels } from "../src/utils/modelVisibility.ts";

test("DeepSeek model choices show only Flash and Pro without changing provider data", () => {
  const input = [
    { id: "deepseek-v4-flash", selected: true },
    { id: "deepseek-flash", selected: false },
    { id: "deepseek-v4-flash-vision-exp", selected: false },
    { id: "deepseek-v4-pro", selected: false },
    { id: "qwen3.8-max", selected: false },
  ];
  const visible = visibleUserModels(input);
  assert.deepEqual(visible.map((model) => model.id), [
    "deepseek-flash", "deepseek-v4-pro", "qwen3.8-max",
  ]);
  assert.equal(visible[0].selected, true);
  assert.equal(input[1].selected, false);
  assert.equal(displayedModelId("deepseek-v4-flash-vision-exp"), "deepseek-flash");
  assert.equal(displayedModelId("qwen3.8-max"), "qwen3.8-max");
});
