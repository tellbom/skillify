import assert from "node:assert/strict";
import test from "node:test";
import {
  answersForQuestionRequest,
  normalizeQuestionRequest,
} from "./opencode-adapter.js";

test("normalizes one OpenCode question and maps a selected label", () => {
  const question = normalizeQuestionRequest({
    requestID: "question-1",
    sessionID: "session-1",
    questions: [{
      header: "API behavior",
      question: "Return 401 or redirect?",
      options: [
        { label: "Return 401", description: "Keep the API response." },
        { label: "Redirect", description: "Send the browser to login." },
      ],
    }],
  });

  assert.ok(question);
  assert.deepEqual(
    answersForQuestionRequest(question, { choice: "Return 401" }),
    [["Return 401"]],
  );
});

test("maps multi-question free text without crossing question boundaries", () => {
  const question = normalizeQuestionRequest({
    id: "question-2",
    sessionID: "session-2",
    questions: [
      { header: "Files", question: "Which files?", options: [], multiple: true },
      { header: "Mode", question: "Strict or compatible?", options: [] },
    ],
  });

  assert.ok(question);
  assert.deepEqual(
    answersForQuestionRequest(question, { answer: "a.py, b.py\nStrict" }),
    [["a.py", "b.py"], ["Strict"]],
  );
  assert.throws(
    () => answersForQuestionRequest(question, { answer: "only one line" }),
    /one non-empty line per question/,
  );
});
