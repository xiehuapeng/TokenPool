import assert from "node:assert/strict";
import test from "node:test";
import { validateCredentials } from "../src/utils/authValidation.ts";

test("login accepts existing credentials without applying registration policy", () => {
  for (const [username, password] of [
    ["ab", "alpha123"],
    ["admin", "plainletters"],
    ["admin", `a1${"x".repeat(64)}`],
  ]) {
    assert.equal(validateCredentials("login", username, password), null);
    assert.notEqual(validateCredentials("register", username, password), null);
  }
});

test("login checks the API length boundaries", () => {
  assert.equal(validateCredentials("login", "ab", "1".repeat(8)), null);
  assert.equal(validateCredentials("login", "a".repeat(64), "x".repeat(256)), null);
  for (const [username, password] of [
    ["a", "password"],
    ["a".repeat(65), "password"],
    ["admin", "short"],
    ["admin", "x".repeat(257)],
  ]) {
    assert.notEqual(validateCredentials("login", username, password), null);
  }
});

test("registration retains username and password requirements", () => {
  assert.equal(validateCredentials("register", "team.user-1", "StrongPass123!"), null);
  assert.notEqual(validateCredentials("register", "_team", "StrongPass123!"), null);
  assert.notEqual(validateCredentials("register", "team", "12345678"), null);
  assert.notEqual(validateCredentials("register", "team", "abcdefgh"), null);
});
