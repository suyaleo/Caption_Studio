모르면 아는 척하지 않는다.
애매하면 바로 구현하지 않고 기준을 먼저 고정한다.
구현했으면 "돌아간다"가 아니라 "쓸 만하다"까지 검증한다.
실패하면 회피하지 않고 원인, 책임, 재작업 계획을 남긴다.
main merge는 사용자 승인 전까지 절대 하지 않는다.
페이지별 dev branch 원칙을 실제로 지킨다.
문서, 코드, 스크린샷, 테스트, 사용자 승인 상태를 분리해서 보고한다.

## Always Load Project Rules

For every repository:

1. Read project root `AGENTS.md` before work.
2. If `START_HERE.md` exists, read it before implementation.
3. If `docs/agent-policy/READING_MAP.md` exists, follow it to select task-specific documents.
4. Produce Bootstrap Report before editing.

## Context Compaction

After compaction, resume, clear, model switch, or agent switch:

1. Do not continue from compressed summary alone.
2. Read `docs/continuity/pre-compact-checkpoint.md` first.
3. Read `docs/continuity/active-work.md` and `docs/continuity/current-goal.md`.
4. Produce Post-Compact Re-entry Report before editing.

## Verification

Do not mark work complete without verification evidence.

If verification cannot be run, state that clearly and mark the work unverified.

## Bad Code

If the same issue repeats or code structure appears wrong:

1. Stop patching.
2. Use bad-code triage.
3. Classify as A Keep, B Partial discard, or C Full rebuild.
4. Do not add features to C-grade code.
