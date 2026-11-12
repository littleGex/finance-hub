import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { parseAmount } = createRequire(import.meta.url)("../../web/parse.js");

test("German thousands dot without decimals", () => {
  assert.equal(parseAmount("1.500"), 1500);
  assert.equal(parseAmount("1.150"), 1150);
  assert.equal(parseAmount("12.500"), 12500);
  assert.equal(parseAmount("1.234.567"), 1234567);
});

test("German decimal comma", () => {
  assert.equal(parseAmount("1.234,56"), 1234.56);
  assert.equal(parseAmount("12,50"), 12.5);
  assert.equal(parseAmount("-96,50"), -96.5);
  assert.equal(parseAmount("€ 1.000,00"), 1000);
});

test("English formats", () => {
  assert.equal(parseAmount("12.50"), 12.5);
  assert.equal(parseAmount("1234.56"), 1234.56);
  assert.equal(parseAmount("1,234.56"), 1234.56);
  assert.equal(parseAmount("1150"), 1150);
});

test("not numbers", () => {
  assert.ok(Number.isNaN(parseAmount("")));
  assert.ok(Number.isNaN(parseAmount("abc")));
});
