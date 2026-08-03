# LMWiki Schema

- 권위 문서는 `map`, `contract`, `decision`, `runbook`, `concept`, `reference` 유형을 사용한다.
- 대화 기억은 `memory`, 장기 협업 Persona는 `persona` 유형을 사용한다.
- 기억은 `l0`, `l1`, `l2`, `l3` 계층과 `distilled_from` 출처 관계를 유지한다.
- `memory.capture: hook`은 Stop 훅에서 L0–L2를 순차 발화한다.
- L3는 최소 두 개의 활성 L1/L2 근거가 있을 때만 발화하며 runbook은 피드백 없는 완료 후보에서 `draft`로 시작한다.
- 모든 기억 문서는 `access` 정책을 가진다.
- 개인·제한 기억은 Git 비추적 로컬 경로에 둔다.
- Markdown과 frontmatter가 원본이며 검색 색인은 재생성 가능한 파생물이다.
