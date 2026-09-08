import assert from "node:assert/strict";
import test from "node:test";
import { chatCompletionsUrl } from "../src/utils/requestUrls.ts";

test("TRAE full URL includes the chat endpoint exactly once after the configured base", () => {
  assert.equal(chatCompletionsUrl("https://gateway.example/v1"), "https://gateway.example/v1/chat/completions");
  assert.equal(chatCompletionsUrl("https://gateway.example/v1/"), "https://gateway.example/v1/chat/completions");
  assert.equal(chatCompletionsUrl("https://gateway.example/team/v1///"), "https://gateway.example/team/v1/chat/completions");
});

test("an unavailable configuration does not invent a usable request URL", () => {
  assert.equal(chatCompletionsUrl(""), "");
  assert.equal(chatCompletionsUrl("   "), "");
});
