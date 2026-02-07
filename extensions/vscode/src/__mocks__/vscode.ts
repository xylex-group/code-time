export const workspace = {
  getConfiguration: () => ({
    get: () => undefined,
  }),
  onDidChangeTextDocument: () => ({ dispose: () => {} }),
  onDidSaveTextDocument: () => ({ dispose: () => {} }),
};
export interface ExtensionContext {
  subscriptions: { dispose(): void }[];
}
export const Uri = {};
export const Range = {};
export const Position = {};
export const window = {};
export const commands = {};
export const languages = {};
export const StatusBarAlignment = {};
export const env = {};
export const version = "1.74.0";
