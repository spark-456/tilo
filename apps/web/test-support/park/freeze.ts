// WEB-1a test support: deep-freeze a value so any write to a shared fixture throws (ES modules are
// strict, so assignment to a frozen property is a TypeError, not a silent no-op).
export function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  }
  return value;
}
