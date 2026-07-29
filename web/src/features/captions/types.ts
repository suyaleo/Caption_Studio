export type CaptionPosition = "top" | "middle" | "bottom";
export type CaptionAlign = "left" | "center" | "right";

export interface CaptionStyle {
  fontFamily: string;
  fontSize: number;
  color: string;
  outlineEnabled: boolean;
  outlineColor: string;
  outlineWidth: number;
  backgroundEnabled: boolean;
  backgroundColor: string;
  position: CaptionPosition;
  align: CaptionAlign;
  offsetX: number;
  offsetY: number;
}

export interface CaptionSegment {
  id: string;
  start: number;
  end: number;
  text: string;
  styleOverride?: Partial<CaptionStyle>;
  confidence?: number | null;
  flags?: string[];
  sourceText?: string;
  sourceLanguage?: string;
  targetLanguage?: string;
}

export interface CaptionProject {
  version: 1;
  projectName: string;
  mediaName: string | null;
  duration: number;
  captions: CaptionSegment[];
  globalStyle: CaptionStyle;
  updatedAt: string;
}

export const DEFAULT_STYLE: CaptionStyle = {
  fontFamily: "Apple SD Gothic Neo",
  fontSize: 48,
  color: "#ffffff",
  outlineEnabled: true,
  outlineColor: "#000000",
  outlineWidth: 2,
  backgroundEnabled: true,
  backgroundColor: "rgba(0,0,0,0.62)",
  position: "bottom",
  align: "center",
  offsetX: 0,
  offsetY: 0,
};

export const CAPTION_FONTS = [
  { value: "Apple SD Gothic Neo", label: "Apple SD Gothic Neo" },
  { value: "BM Dohyeon", label: "배민 도현" },
  { value: "BM Jua", label: "배민 주아" },
  { value: "Nanum Gothic", label: "나눔고딕" },
  { value: "Nanum Myeongjo", label: "나눔명조" },
  { value: "Arial", label: "Arial" },
  { value: "Georgia", label: "Georgia" },
  { value: "Courier New", label: "Courier New" },
] as const;

export const SEED_CAPTIONS: CaptionSegment[] = [
  { id: "caption-1", start: 0, end: 3, text: "오늘, 우리의 이야기가 시작됩니다" },
  { id: "caption-2", start: 3, end: 6.2, text: "서로를 믿고 아껴온 시간들" },
  { id: "caption-3", start: 6.2, end: 9.4, text: "그 모든 순간이 모여" },
  { id: "caption-4", start: 9.4, end: 12.8, text: "이날을 더욱 빛나게 합니다" },
  { id: "caption-5", start: 12.8, end: 16.4, text: "함께 걸어갈 새로운 길" },
  { id: "caption-6", start: 16.4, end: 20, text: "저희의 앞날을 축복해주세요" },
];

export function mergedStyle(
  globalStyle: CaptionStyle,
  segment?: CaptionSegment,
): CaptionStyle {
  return { ...DEFAULT_STYLE, ...globalStyle, ...(segment?.styleOverride ?? {}) };
}
