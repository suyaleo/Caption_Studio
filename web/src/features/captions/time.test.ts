import { describe, expect, it } from "vitest";
import { formatClock, formatShortClock } from "./time";

describe("caption time formatting", () => {
  it("does not display a binary floating-point value one millisecond early", () => {
    expect(formatShortClock(16.4)).toBe("00:16.400");
    expect(formatClock(16.4)).toBe("00:00:16,400");
  });

  it("carries rounded milliseconds into the next second", () => {
    expect(formatShortClock(59.9996)).toBe("01:00.000");
    expect(formatClock(59.9996)).toBe("00:01:00,000");
  });
});
