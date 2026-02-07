import * as vscode from "vscode";

const USER_AGENT = "CodeTime Client";
const DEFAULT_BASE_URL = "http://localhost:9492";

export const EVENT_TYPES = [
  "activateFileChanged",
  "editorChanged",
  "fileSaved",
  "fileAddedLine",
  "fileCreated",
  "fileEdited",
  "changeEditorSelection",
  "changeEditorVisibleRanges",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export const EVENT_LOG_PATH = "/v3/users/event-log";

function isValidEventType(s: string): s is EventType {
  return (EVENT_TYPES as readonly string[]).includes(s);
}

/** Normalize and validate base URL; returns default if invalid. */
function normalizeBaseUrl(raw: string | undefined): string {
  const s = (raw ?? DEFAULT_BASE_URL).trim().replace(/\/+$/, "");
  if (s.startsWith("https://") || s.startsWith("http://")) {
    return s;
  }
  return DEFAULT_BASE_URL;
}

/** Build event body for POST /v3/users/event-log (for tests and sendEvent). */
export function buildEventBody(
  eventType: EventType,
  payload: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    event_type: eventType,
    editor: "vscode",
    platform: process.platform,
    ...payload,
  };
}

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration("codetimeProxy");
  const baseUrl = normalizeBaseUrl(config.get<string>("baseUrl"));
  const enabled = config.get<boolean>("enabled") ?? true;

  if (!enabled) {
    return;
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((e) => {
      sendEvent(baseUrl, "fileEdited", { contentChanges: e.contentChanges.length });
    }),
    vscode.workspace.onDidSaveTextDocument(() => {
      sendEvent(baseUrl, "fileSaved", {});
    })
  );
}

function sendEvent(
  baseUrl: string,
  eventType: EventType,
  payload: Record<string, unknown>
): void {
  if (!isValidEventType(eventType)) {
    console.warn("[codetime-proxy] Invalid event type:", eventType);
    return;
  }
  try {
    const url = baseUrl + EVENT_LOG_PATH;
    const body = buildEventBody(eventType, payload);
    // TODO: POST to url with User-Agent: CodeTime Client and optional Authorization
    console.log("[codetime-proxy]", eventType, url, body);
  } catch (err) {
    console.error("[codetime-proxy] sendEvent failed:", err);
  }
}

export function deactivate(): void {}
