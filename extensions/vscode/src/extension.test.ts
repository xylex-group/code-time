import {
  EVENT_LOG_PATH,
  EVENT_TYPES,
  buildEventBody,
  type EventType,
} from "./extension";

describe("CodeTime VS Code extension", () => {
  describe("EVENT_TYPES", () => {
    it("has exactly 8 event types", () => {
      expect(EVENT_TYPES).toHaveLength(8);
    });

    it("includes expected event types", () => {
      expect(EVENT_TYPES).toContain("fileSaved");
      expect(EVENT_TYPES).toContain("fileEdited");
      expect(EVENT_TYPES).toContain("activateFileChanged");
      expect(EVENT_TYPES).toContain("editorChanged");
      expect(EVENT_TYPES).toContain("changeEditorSelection");
      expect(EVENT_TYPES).toContain("changeEditorVisibleRanges");
      expect(EVENT_TYPES).toContain("fileAddedLine");
      expect(EVENT_TYPES).toContain("fileCreated");
    });
  });

  describe("EVENT_LOG_PATH", () => {
    it("is the event-log path", () => {
      expect(EVENT_LOG_PATH).toBe("/v3/users/event-log");
    });
  });

  describe("buildEventBody", () => {
    it("returns body with event_type, editor, platform", () => {
      const body = buildEventBody("fileSaved");
      expect(body.event_type).toBe("fileSaved");
      expect(body.editor).toBe("vscode");
      expect(body.platform).toBeDefined();
      expect(typeof body.platform).toBe("string");
    });

    it("merges extra payload", () => {
      const body = buildEventBody("fileEdited", { contentChanges: 3 });
      expect(body.event_type).toBe("fileEdited");
      expect(body.contentChanges).toBe(3);
    });
  });
});
