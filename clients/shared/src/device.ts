/** Random, pseudonymous device ID used only for watches, alerts and rate limits. */
const DEVICE_RE = /^[A-Za-z0-9-]{8,64}$/;

export function newDeviceId(): string {
  return globalThis.crypto.randomUUID();
}

export function isValidDeviceId(id: unknown): id is string {
  return typeof id === "string" && DEVICE_RE.test(id);
}

/** Get-or-create with any async key/value store (chrome.storage, expo-secure-store...). */
export async function ensureDeviceId(
  get: () => Promise<string | null | undefined>,
  set: (id: string) => Promise<void>,
): Promise<string> {
  const existing = await get();
  if (isValidDeviceId(existing)) return existing;
  const id = newDeviceId();
  await set(id);
  return id;
}
