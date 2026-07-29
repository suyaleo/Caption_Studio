import { describe, expect, it } from "vitest";
import { captionsToSrt, captionsToVtt, parseCaptionText } from "./formats";

describe("caption formats", () => {
  it("parses SRT and keeps multiline caption text", () => {
    const result = parseCaptionText(`1\n00:00:01,000 --> 00:00:03,250\n첫 번째 줄\n두 번째 줄\n`);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ start: 1, end: 3.25, text: "첫 번째 줄\n두 번째 줄" });
  });

  it("roundtrips SRT timing and text", () => {
    const source = `1\n00:00:00,000 --> 00:00:02,500\n안녕하세요\n\n2\n00:00:03,000 --> 00:00:05,000\n다시 만나요\n`;
    const first = parseCaptionText(source);
    const second = parseCaptionText(captionsToSrt(first));
    expect(second.map(({ start, end, text }) => ({ start, end, text }))).toEqual(
      first.map(({ start, end, text }) => ({ start, end, text })),
    );
  });

  it("serializes valid WebVTT", () => {
    const output = captionsToVtt([{ id: "one", start: 0, end: 1.2, text: "시작" }]);
    expect(output).toContain("WEBVTT");
    expect(output).toContain("00:00:00.000 --> 00:00:01.200");
  });
});
