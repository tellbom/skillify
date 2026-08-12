import assert from "node:assert/strict";
import test from "node:test";
import {
  CLAUDE_NATIVE_SETTING_SOURCES,
  answersForClaudeQuestions,
  shouldEmitClaudeProviderEvent,
} from "./claude-adapter.js";

test("loads Claude Code native settings without a Skillify model override", () => {
  assert.deepEqual(
    CLAUDE_NATIVE_SETTING_SOURCES,
    ["user", "project", "local"],
  );
});

test("does not forward Claude thinking token progress as timeline events", () => {
  assert.equal(shouldEmitClaudeProviderEvent({
    type: "system",
    subtype: "thinking_tokens",
  }), false);
  assert.equal(shouldEmitClaudeProviderEvent({
    type: "provider_event",
    subtype: "tool_progress",
  }), true);
});

test("maps a Claude question answer to its original question key", () => {
  const input = {
    questions: [{
      header: "API behavior",
      question: "Return 401 or redirect?",
      options: [{ label: "Return 401" }, { label: "Redirect" }],
    }],
  };

  assert.deepEqual(
    answersForClaudeQuestions(input, { choice: "Return 401" }),
    { "Return 401 or redirect?": "Return 401" },
  );
});

test("requires one answer line for each Claude question", () => {
  const input = {
    questions: [
      { header: "API", question: "Return code?", options: [] },
      { header: "Docs", question: "Update docs?", options: [] },
    ],
  };

  assert.deepEqual(
    answersForClaudeQuestions(input, { answer: "401\nYes" }),
    { "Return code?": "401", "Update docs?": "Yes" },
  );
  assert.throws(
    () => answersForClaudeQuestions(input, { answer: "401" }),
    /one non-empty line per question/,
  );
});
