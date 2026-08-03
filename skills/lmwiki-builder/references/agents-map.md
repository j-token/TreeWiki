# AGENTS.md 지도 계약

`AGENTS.md`는 계약 본문을 복제하지 않고 코드 영역, 필수 계약, 검증 진입점을 연결한다.

## 필수 frontmatter

```yaml
---
id: MAP-ROOT-001
title: 저장소 지식 지도
type: map
status: active
authority: normative
topics:
  - repository-knowledge-management
summary: 저장소의 코드 영역과 필수 계약 및 검증 진입점을 연결한다.
applies_to:
  - "**"
read_when:
  - 저장소 작업을 시작할 때
relations: []
reviewed: YYYY-MM-DD
embedding:
  mode: local_only
  content: full
---
```

## 필수 본문

1. 관할 범위
2. 영역별 코드·문서 시작점
3. 변경 전에 읽을 활성 계약
4. 테스트·린트·수동 검증 명령
5. 더 구체적인 하위 `AGENTS.md`
6. 변경 유형별 문서 갱신 조건

루트 지도에서 주요 코드 영역까지 최대 2번의 지도 링크로 도달하게 한다. 하위 지도는 상위 규칙을 반복하지 않고 지역 정보만 추가한다.

## 읽기 순서

1. 작업 대상과 가장 가까운 지도
2. 루트까지의 상위 지도
3. 지도에서 필수라고 지정한 활성 계약
4. 계약이 연결한 결정과 검증 근거

지도에 계약 내용을 복사하지 않는다. 문서 ID와 상대 경로를 함께 기록해 사람과 도구가 모두 찾을 수 있게 한다.
